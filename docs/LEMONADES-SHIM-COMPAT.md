# 一加 9R：Shim 注册与版本兼容

2026-10-25。已实现并离线验证有容量限制的 Shim 注册器、原厂版本选择行为及失败边界，
普通/LP5 两套候选 FD 均已重建。**未连接或启动手机，未实现可工作的 Scheduler，也未启动 iOS。**
本记录接续 [HOB 审查](LEMONADES-HOB-AUDIT.md)。最新产物为下文 `shim-*`。

## 实际实现

`uefi/lemonades/mu-shim.patch` 在既有 HOB 修复之后应用；参考 Mu checkout 保持不变。
构建输入记录补丁哈希，最终产物记录编译工具、Python 包版本及所有原厂输入哈希。

原先 `ShimInstallLib` 无条件返回成功，却不保存任何库；`ShimLoadLib` 只按名称返回两个
内置接口，忽略请求版本。现在：

- 注册表最多 32 项，含 UEFI Config Lib 1.2、SerialPort Lib 1.1 两项内置库。
  新库按调用顺序追加，重复名称和版本也不会覆盖旧项。
- 注册名称复制到 1,024 字节的静态池；接口本身由调用者持有，必须保持有效。
  名称大小包括 NUL 后按 4 字节对齐。内置名称用静态字符串，不消耗动态名称池。
- 拒绝空名称、空接口；容量不足或复制失败时返回错误，保持已发布的条目和计数不变。
- 通过 `SynchronizationLib` 的原子比较交换保护整个读写过程。遇到重入或竞争返回
  `EFI_NOT_READY`，不等待被中断调用者释放锁，不暴露尚未写完的条目。
  这是明确的保守扩展，不是从原厂证明出的并发 ABI；调用方需处理失败/重试。
- 名称不区分大小写。请求版本规则与所审查的 H.30 函数一致：

| 请求/现有注册情况 | 状态 | 输出接口 |
| --- | --- | --- |
| 请求版本 0 | EFI_SUCCESS | 最早注册的同名项 |
| 有精确版本 | EFI_SUCCESS | 最早注册的精确版本，即使前面已有较新版本 |
| 无精确版本，但有同主版本且版本更高的项 | EFI_NO_MAPPING (`0x8000000000000011`) | 最早注册的兼容项 |
| 只有较旧版本、不同主版本，或没有该名称 | EFI_NOT_FOUND | NULL |

`EFI_NO_MAPPING` 是错误状态，不是成功警告。保留接口输出并不代表调用者一定会接受回退。
版本高 16 位作为主版本；0 是通配请求。未把不同主版本的接口当作兼容接口。

注册器服务于早期固件初始化，不提供卸载或 ExitBootServices 后的生命周期承诺。
它不创建 Qualcomm Scheduler、硬件驱动或那四个仍未确认提供者的协议。

## 原厂函数仿真与对照测试

新增 `shim_oracle.py` 使用固定 `unicorn==2.1.4`，将原厂 SEC 的 TE section 映射到独立的
AArch64 仿真 RAM，并只调用已审查的 Install (`0x9FC1690C`) 和 Load (`0x9FC169FC`) 函数。
字符串辅助函数也由原厂指令执行。分区和 section 哈希校验之外，还固定了两套 SEC 的完整哈希。
代码页只读可执行，数据和栈不可执行，不映射设备 MMIO；每次调用有指令数量和时间上限。

测试人工构造了空注册表、栈和参数，再注册与 Mu 一致的两个内置接口。这不是原厂 SEC 启动，
没有运行 HOB 构造、Scheduler 或整个固件，也不能验证实际时序/中断/缓存状态。

`check-shim.py` 会依序应用真实构建补丁，提取最终 Shim 注册表及全部函数，使用宿主服务替身
编译成带 ASan/UBSan 的 C 程序。10 个场景包括固定版本向量和固定种子的操作序列；
**每套原厂输入各 1,135 次操作，共 2,270 次，对比状态码和接口指针一致。**
覆盖通配、精确版本优先、兼容回退、主版本拒绝、重复注册、大小写、容量耗尽和未知名称。

另外的边界测试覆盖 NULL、空名称、调用者修改原名称、名称池恰好填满、超长名称、
注册表填满、复制失败、竞争/重入时快速失败，以及失败后释放保护状态。
主机原子操作替身验证了保护路径；没有宣称经过实机多核并发压力测试。

发现并复现一个不应照搬的原厂边界缺陷：其名称预留空间按 `(strlen + 3) & ~3` 计算，
没有为长度为 4 的倍数的名称单独预留 NUL。例如先注册 `AAAA`、再注册 `BBBBB`，后者
覆盖前者的终止符，随后原厂查找 `AAAA` 返回 NOT_FOUND。新实现按 `strlen + 1` 分配，
相同场景查找成功。差分场景避开该已知缺陷，独立边界测试验证修复。
原厂未命中时可能保留旧输出指针；新实现继续保证失败输出清空（兼容回退例外）。
因此“比对通过”指上述有定义的场景，不是所有错误输入或内存布局与原厂完全一致。

## Scheduler 初始化的新证据

扩展后的 `inspect-hob-paths.py` 固定了初始化函数 `0x9FC21650..0x9FC21797` 的指令摘要、
配置名称和调用位置，并校验两套原厂 `uefiplat.cfg`：

| 配置 | 原厂值 |
| --- | --- |
| EnableMultiThreading | 1 |
| MaxCoreCnt | 8 |
| EarlyInitCoreCnt | 1 |
| Sched Heap | 基址 `0x9BC00000`，大小 `0x00400000` |

原厂 SEC 在 `0x9FC0D65C` 调用上述函数；它先查询 EnableMultiThreading，失败或为 0 时
跳过 Scheduler HOB 构造路径。启用后查询 Sched Heap、核心数，读取库版本；
`0x9FC21730` 才调用 HOB 构造器，之后仍有 `0x9FC215D0`、`0x9FC2522C`、
`0x9FC2694C` 等调用及后续控制转移。这里只确认调用顺序，没有为未完整理解的函数命名。

两套原厂配置默认启用该路径；当前 Mu 设备配置中保留相同的开关及堆区域，却没有因此得到
原厂 Scheduler 初始化。固定 Kona `PlatformSec.c` 主要处理看门狗及显示 SMMU，
配置值本身不能生成 Scheduler 服务。本轮没有改成 0 来掩盖缺失，也没有复用会被替换的
原厂 SEC 地址。下一步需要继续审查完整状态建立、函数依赖和内存生命周期。

## 验证与产物

49 项项目回归测试通过，两套 BaseTools 各 309 项通过；完整 AArch64 FD 构建和拆包检查通过。
两套各 3 MiB、101 个 FFS、84 个 PE 驱动、42 个 DEPEX GUID、0 个悬空 APRIORI 项。
46 个原厂驱动与 4 项 RAW 内容不变。本轮未改诊断 EFI，未重复之前的 QEMU EFI 测试；
新 FD 未在 QEMU 或实机启动。

| 变体 | 文件 | SHA-256 |
| --- | --- | --- |
| 普通 XBL | `out/lemonades/artifacts/shim-xbl/lemonades-probe.fd` | `76b6dfb5a5f816e144ae525b382b7c5e60291ce1c07d3ec5c7ca99140992744f` |
| LP5 | `out/lemonades/artifacts/shim-xbl_lp5/lemonades-probe.fd` | `9ee95fbd1a943d2b5c7f27e18354f6a14e1f64487fbf44332ce35d3e63b2cb8c` |

证据在 `out/lemonades/shim-audit/{differential,hob-paths,fd-xbl,fd-xbl_lp5}.json`，
构建来源在各产物的 `verification.json`，日志为 `out/lemonades/shim-*.log`。
`hob-*` 为前一版产物，保留对照。

```sh
out/lemonades/mu-venv/bin/python -m pip install -r tools/lemonades/requirements-uefi-lock.txt
out/lemonades/mu-venv/bin/python tools/lemonades/check-shim.py \
  --output out/lemonades/shim-audit/differential.json
out/lemonades/mu-venv/bin/python tools/lemonades/inspect-hob-paths.py \
  out/lemonades/stock/LE2101_14.0.0.2301 --output out/lemonades/shim-audit/hob-paths.json
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'
```

完整构建继续使用 `prepare-build.py` → BaseTools make → `build-fd.sh` → `audit-fd.py`。
本轮输入 overlay 是 `uefi-audit-overlay` / `uefi-audit-lp5-overlay`，最终构建目录为
`mu-shim-final-build` / `mu-shim-final-build-lp5`。复现时选新的输出目录，避免旧拆包内容混入。
