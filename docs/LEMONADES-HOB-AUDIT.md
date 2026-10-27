# 一加 9R：Qualcomm HOB 与剩余协议追踪

后续 Shim 注册/版本修复与最新 `shim-*` 产物见 [Shim 兼容记录](LEMONADES-SHIM-COMPAT.md)。
本页保留前一轮状态。

2026-10-25。完成原厂 SEC/EnvDxe 静态路径追踪、Mu 的确定性错误修复及普通/LP5 两套 FD 重建。
**尚未在 9R 上运行这些固件；Scheduler 服务的生命周期和厂商协议安装结果仍未验证。**
本记录接续 [协议依赖审查](LEMONADES-PROTOCOL-AUDIT.md)，下列 `hob-*` 是最新候选产物。

## 原厂初始化路径

输入为已提取的 `LE2101_14.0.0.2301`，固定分区和 section 哈希。新增
`trace-hobs.py` 正确区分 PE 和 TE 的地址映射：TE 原始数据偏移需要减去
`StrippedSize - 40`，但首选虚拟地址仍为 `ImageBase + section RVA`。
原厂 SEC 的 ImageBase 为 `0x9FC01000`，不能直接把整个 FD 基址当作 TE 的 ImageBase。

两套输入各有 93 个可执行镜像包含选定的 HOB/Kernel GUID，得到 191 个基本块内的常量地址引用。
脚本跟踪 ADR/ADRP、立即数 ADD 和寄存器 MOV；遇到寄存器覆盖、跳转、调用或无法解码的数据时
清除相应状态。这是静态引用线索，不是完整数据流分析或协议提供者判定。

以下路径经反汇编审查，并由 `inspect-hob-paths.py` 对两套固件的指令区间、调用指令、GUID、
接口表及库名称重新核对。地址是原厂首选加载地址；EnvDxe 列出的是 RVA。

| 路径 | 静态证据 | 限制 |
| --- | --- | --- |
| SEC → Scheduler HOB | `0x9FC21730` 调用 `0x9FC2748C`；后者将 `0x9FC34660` 放到栈上，以长度 8 调用 `0x9FC1600C` | 未证明运行时执行成功 |
| GUID HOB 构造 | `0x9FC15FA8` 分配类型 4、长度为 payload + `0x18` 的 HOB，复制 GUID；`0x9FC1600C` 再复制 payload | 函数名称为依据行为的解释，原厂无符号 |
| Scheduler 接口表 | `0x9FC34660` 首项为 `0x10005`，后接 Interrupt、Timer、Thread、Event、Mutex、Sem、Spinlock、MpCpu、WDog、GetLibVersion、Lock 的 11 项地址 | 表内地址不等于存活的服务 |
| SEC → Shim HOB | `0x9FC0D9C0` 调用 `0x9FC16B10`，后者创建指向 `0x9FC34310` 的 8 字节指针 HOB | 原厂 Shim 的注册状态也属于 SEC 内存 |
| Shim 接口表 | 版本 `0x10001`，Install 为 `0x9FC1690C`，Load 为 `0x9FC169FC` | Mu 只实现两个静态库，不等价于原厂注册器 |
| EnvDxe → Scheduler | 入口构造链 `0x1450` 调用 `0x8834`；先用 Boot Services `+0x140` 的 LocateProtocol 查 Kernel 协议，再经 `0x88FC` 读取 Scheduler GUID HOB 的 `+0x18` 数据 | 缺失时此构造函数仍返回 EFI_SUCCESS；不能据此断言整驱动成功或必然失败 |
| EnvDxe → Shim | `0xC888` 查 Shim HOB；`0x3C20`、`0x3E4C` 调用表偏移 `0x10` 的 LoadLib | 库名分别为 SerialPort Lib、UEFI Config Lib，请求版本均为 0 |

Scheduler HOB GUID 为 `8EC2BD8D-56D7-49EF-8796-631778F8EBF8`，
Shim HOB GUID 为 `BEDAEABC-5E70-4D66-9733-213D072B9D04`。
InfoBlk GUID 与 EnvDxe 的文件 GUID 恰好相同；APRIORI 中出现它不能作为构造 HOB 的证据。

**不能把 `0x9FC34660` 写进新 HOB 作为修复。** 该表及其函数/数据地址落在原厂 SEC 中，
而新候选 FD 占用 `0x9FC00000..0x9FF00000`。替换该区域后，这些旧地址不再有有效性保证。
当前 9R 内存图没有 `FD Reserved` / `FD_Reserved`，Mu 的旧扫描器不会恢复 Scheduler 或
DTB Extension 地址。本轮保持这一状态，没有伪造接口、保留区或 HOB。

原厂提取的 section 中未找到 FvList、DtbExtension 两个 GUID 的完整字节，因此没有将
Mu 在其他平台使用的这两项当作本机已证实的原厂 ABI。

## 剩余协议提供者

扫描范围已从 PE 扩展到全部提取 section，包括 SEC 的 TE 和 RAW。
两套固件中以下 GUID 都仅在 DEPEX 命中，未发现可确认的安装路径：

| GUID | 原厂 DEPEX 消费者 |
| --- | --- |
| `0F9B9E33-B8E4-4E6D-A83E-2B6710A1CC24` | PILProxyDxe |
| `47861DFF-556F-4269-9B28-062EC3ECB30D` | EnvDxe、UFSDxe、DisplayDxe |
| `A966CC4F-EE6C-424D-A762-8ED3B5A4A501` | EnvDxe、UFSDxe、DisplayDxe |
| `76B95DAD-1E66-4D98-9CE7-B294D9596895` | UsbfnDwc3Dxe |

此处包含原厂 DisplayDxe，范围大于候选固件驱动集。不能排除运行时构造 GUID、提取范围外的
服务或未使用的模板依赖。APRIORI 也可能跳过 DEPEX 检查。未安装空协议或放宽表达式来隐藏问题。

## 已落实的代码修复

`uefi/lemonades/mu-hob.patch` 由隔离构建导出后应用，不改动参考 Mu checkout。
`prepare-build.py` 检查补丁正向应用及反向可应用状态，并记录补丁 SHA-256。

1. **FV 列表越界。** 上游按字节分配 `0x4A × 8 = 592` 字节，却在 `UINTN *` 上计算
   `0x18 + i × 0x48` 偏移；AArch64 的第二项已写到偏移 768，超出分配。
   改为字节指针计算，保留原有分配大小和条目 stride，并增加末项范围静态断言。
   这修复 Mu 自身的内存错误，不证明 9R 原厂需要该列表。
2. **锁版本和失败清理。** 先检查 Scheduler 主版本 1、版本至少 `0x10005`、Lock 表及
   Init/Destroy 回调。句柄预先置空，拒绝“成功但空句柄”；任一后续初始化失败时按逆序销毁
   已成功创建的锁，再释放列表。检查不负责验证任意物理地址是否可读，不能使旧 SEC 指针有效。
3. **配置字符串错误状态。** 修正 `PlatformType != "NULL"` 的指针比较，改为内容判断。
   未配置时返回 NOT_READY；容量不足时返回 BUFFER_TOO_SMALL，不修改目标缓冲区；
   返回真实的安全复制状态。保留上游 EntryValueLength 的输入容量语义，不新增查询模式。
4. **Shim 失败输出。** LoadLib 在输出指针有效时先清空它，避免未知库或无效名称留下旧接口。
   保留版本 0 的现有成功路径。

没有声称修复完整 Shim ABI：原厂 LoadLib 含精确版本及同主版本回退选择，Mu 仍忽略请求版本；
Mu 的 InstallLib 仍直接返回成功而不注册。为这些行为设计替代实现之前，还需审查实际消费者对
返回状态和注册生命周期的要求。旧 `XblProtocols.c` 的启发式扫描也存在未限定函数扫描长度、
寄存器追踪及指针有效性问题；当前 9R 配置不调用其扫描循环，不能通过增加 FD Reserved 来启用它。

## 验证与产物

49 项项目回归测试通过，含新增的 TE 地址映射、畸形范围、源寄存器追踪、32 位寄存器覆盖、
调用/分支边界及证据摘要变更检查。主机测试直接提取并编译补丁后的实际 C 函数，ASan/UBSan
覆盖 8 个位置的初始化错误、8 个位置的空句柄成功、内存分配失败、完整字节布局、ABI 检查、
配置容量边界和 Shim 失败输出。使用的是模拟服务，不等于 Qualcomm 固件执行测试。

两套完整 AArch64 构建成功，各自 BaseTools 309 项测试通过；最终 FD 再次拆包，均为 3 MiB、
101 个 FFS、84 个 PE 驱动、42 个 DEPEX GUID、0 个悬空 APRIORI 项。
46 个原厂驱动和 4 项 RAW 的 section 字节保持不变。
本轮没有修改诊断 EFI，因此没有重复此前的 QEMU EFI 测试；新 FD 未在 QEMU 或手机中启动。

| 变体 | 新 FD | SHA-256 |
| --- | --- | --- |
| 普通 XBL | `out/lemonades/artifacts/hob-xbl/lemonades-probe.fd` | `edc7980d7b37d37687b92beaba21cda6eddb4bf501d32a28addf5d46ff0afa0e` |
| LP5 | `out/lemonades/artifacts/hob-xbl_lp5/lemonades-probe.fd` | `6e42eb4f6a1b9a93ad724e1277478b3464ea2ea153912a166fe374dfc0ea073c` |

离线证据：`out/lemonades/hob-audit/{trace,paths,fd-xbl,fd-xbl_lp5}.json`。
构建记录与来源哈希在各产物的 `verification.json`，日志为 `out/lemonades/hob-*.log`。
`audit-*` 旧产物保留作对照；没有生成或刷写可安装的 iOS 镜像。

## 复现

分析环境固定 `capstone==5.0.6`、`pefile==2024.8.26`，已加入 `requirements-uefi-lock.txt`。

```sh
out/lemonades/mu-venv/bin/python -m pip install -r tools/lemonades/requirements-uefi-lock.txt
out/lemonades/mu-venv/bin/python tools/lemonades/trace-hobs.py \
  out/lemonades/stock/LE2101_14.0.0.2301 --output out/lemonades/hob-audit/trace.json
out/lemonades/mu-venv/bin/python tools/lemonades/inspect-hob-paths.py \
  out/lemonades/stock/LE2101_14.0.0.2301 --output out/lemonades/hob-audit/paths.json
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'
python3 tools/lemonades/check-hob-compat.py
```

重新构建使用新的输出目录（prepare-build 和 audit-fd 会拒绝覆盖已有目录）。以下是本轮执行的路径：

```sh
out/lemonades/mu-venv/bin/python tools/lemonades/prepare-build.py \
  --overlay out/lemonades/uefi-audit-overlay --output out/lemonades/mu-hob-build
make -C out/lemonades/mu-hob-build/Mu_Basecore/BaseTools -j8
bash tools/lemonades/build-fd.sh "$PWD/out/lemonades/mu-hob-build"
out/lemonades/mu-venv/bin/python tools/lemonades/audit-fd.py \
  out/lemonades/mu-hob-build --output out/lemonades/artifacts/hob-xbl
```

LP5 对应 overlay 为 `uefi-audit-lp5-overlay`，构建目录 `mu-hob-build-lp5`，产物 `hob-xbl_lp5`。
下一阶段的离线重点是 Scheduler 生命周期、更多 Shim 消费者及实际协议安装调用链；实机阶段仍需
确认内存占用、HOB 传递和各驱动的返回状态。
