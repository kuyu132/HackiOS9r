# 一加 9R：协议依赖与初始化审查

后续 HOB 追踪与最新 `hob-*` 产物见 [Qualcomm HOB 审查](LEMONADES-HOB-AUDIT.md)。

2026-10-25。本轮完成第一轮静态审查、可确定的代码修正及两套 FD 重建。
**没有执行手机上的厂商驱动，未证明 UEFI、XNU 或 iOS 能在 9R 启动。**

## 实际发现与修正

### APRIORI 与 DEPEX

从最终 FD 读取 APRIORI 的 GUID 数组，而非只搜索工程文本，发现旧产物的 79 项中有
3 项不存在于 FV：`TzDxe`、`PILDxe`、`GpiDxe`。其实际 DXE include 已注释，APRIORI
却仍保留。生成器现在移除这三项，保留其他既有顺序；修订后的数组为 76 项，悬空项为 0。
这会消除清单不一致，不代表此前必然会崩溃：Mu Dispatcher 对未发现的 GUID 不会调度。
没有为填补清单而加入未经审查的驱动。

已实现严格 DEPEX 解析：PUSH GUID、AND/OR/NOT、TRUE/FALSE、END、BEFORE/AFTER 和 SOR。
空缺 DEPEX 按“需要全部架构协议”记录，不等同 TRUE；BEFORE/AFTER 的 GUID 是文件标识。
应用程序和 core 排除在 DXE 驱动调度分析之外。两套修订 FD 各有 84 个 PE 驱动文件，
DEPEX 共引用 42 个不同协议 GUID；75 个驱动位于强制顺序中。

APRIORI 会跳过 DEPEX，这是 [UEFI PI 的调度规则](https://uefi.org/specs/PI/1.8/V2_DXE_Dispatcher.html#the-a-priori-file)，
也与固定 Mu 版本 `MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c` 一致。因此保留原厂
DEPEX 并不代表调度时会等待这些协议。原厂本身也把 EnvDxe 放在它的一些 DEPEX 项之前；
不能直接根据这些表达式重排整个启动链。

当前在候选 PE（排除诊断应用的观察表）和原厂 PE 中均没有找到以下 GUID 的完整字节：

| GUID | 引用的驱动 |
| --- | --- |
| `0F9B9E33-B8E4-4E6D-A83E-2B6710A1CC24` | PILProxyDxe |
| `47861DFF-556F-4269-9B28-062EC3ECB30D` | EnvDxe、UFSDxe |
| `A966CC4F-EE6C-424D-A762-8ED3B5A4A501` | EnvDxe、UFSDxe |
| `76B95DAD-1E66-4D98-9CE7-B294D9596895` | UsbfnDwc3Dxe |

这是待核查项，不能据此判定运行时一定缺失，也不能把找到 GUID 字节的文件直接当成提供者。
GUID 可能被构造、由其他 FV/TE 或核心服务提供，或者只是不会被检查的模板依赖。
报告保留每个引用、现有 PE 和被省略的原厂 PE 中的字节命中，全部标为未确认提供者。

### USB Device 协议 ABI

对两套 H.30 原厂 `UsbDeviceDxe` 的 PE 做了函数表及调用点检查：

- GUID 为 `D9D9CE48-44B8-4F49-8E3E-2A3B927DC6C1`，表位于 RVA `0xE0D8`。
- Revision 为 `0x10000001`，随后有 9 个落在可执行 section 内的函数指针。
  最后一项 `StartEx` 位于表偏移 `0x48`，目标 RVA `0x1C54`。
- 入口初始化链经过 RVA `0x1450` 到 `0x1FAC`；`0x1FC8`、`0x1FCC` 分别形成 GUID 和
  函数表地址，`0x1FD4` 取 Boot Services 偏移 `0x148` 的 InstallMultipleProtocolInterfaces，
  `0x1FE0` 调用它。两套输入匹配同一段已审查指令字节。
- 表布局与固定 Mu `QcomPkg/Include/Protocol/EFIUsbDevice.h` 及 loader 的声明一致。
  这只证明静态接口布局和安装调用点，不证明安装返回成功或 USB 控制器可运行。

新增 `inspect-usb-abi.py` 会校验原厂 section 哈希、架构、表内容及上述指令字节；
换固件后不匹配会报错，需要重新审查，不会按偏移修改驱动。
9R loader 现在在访问 StartEx 前检查接口版本，并检查要用的函数指针是否为空。

### Framebuffer 初始化

上游 SimpleFb 使用未初始化的内存区域描述符，且忽略两次查找的返回值；找不到区域时
仍可能使用垃圾地址。另一个错误路径会在第一次 Mode 分配失败后解引用空的 Mode。
已在隔离构建中通过 `mu-initialization.patch` 修正：

- 初始化描述符；仅在第一种名称找不到时尝试下划线别名，并检查返回状态。
- 检查区域大小、像素深度、乘法和地址范围，防止声明的 framebuffer 超出保留区。
- 修正分配失败后的清理、清理后的空指针状态，并使用 UINTN 计算 framebuffer 大小。

主机故障注入测试直接编译补丁后的两个实际函数，覆盖名称查找失败、过小区域、地址溢出、
非法深度、大尺寸、第一/第二次分配失败和重复清理，ASan/UBSan 通过。
完整 AArch64 固件也已重编译。没有据此确认实际 splash 地址、stride 或像素格式。

## 新增运行时诊断

诊断 EFI 在尝试 USB 前，用 LocateProtocol 查询审计中的 42 个 GUID，将状态码和接口地址
写入原有日志。只查询存在性，不调用这些接口。后续实机日志可以用于区分“固件中有文件”与
“驱动成功安装协议”，但存在性本身仍不等于硬件准备完成。

观察表来自 `common/lemonades/protocol_watch.h`，由审计脚本生成。静态审计刻意排除该应用
中的观察表常量，避免把新增诊断数据误判为协议提供者。QEMU 中已运行新 EFI，观察表日志
正常生成；QEMU 没有模拟 Qualcomm USB 或一加硬件。

## 产物与复现

| 输入 | 新 FD | SHA-256 |
| --- | --- | --- |
| 普通 XBL | `out/lemonades/artifacts/audit-xbl/lemonades-probe.fd` | `c365392944e1d97a63e6856ce105d7fb015738c8c4b643ab52dc16d5ee0863e7` |
| LP5 | `out/lemonades/artifacts/audit-xbl_lp5/lemonades-probe.fd` | `edf9aecf1caa5eb5d97d48c4956ba44282b68c0d4fc885064b6d911616ae93b2` |

两者均为 3 MiB，含 101 个 FFS 文件。46 个原厂驱动和 4 项 RAW 配置保持来源字节不变。
新 EFI 为 22,016 字节，SHA-256：
`0cc13a0b599013761ee36197593a07fb7d10d7810710127c8d8ff897a64433cc`。
旧版 `artifacts/xbl`、`artifacts/xbl_lp5` 留作对照，不是本轮修订产物。

报告：`out/lemonades/protocol-audit/{before-xbl,after-xbl,after-xbl_lp5,usb-abi}.json`。
各产物的 `verification.json` 保存来源、构建参数和哈希；新版验证器还拒绝悬空 APRIORI 项。

```sh
python3 tools/lemonades/protocol_audit.py out/lemonades/artifacts/audit-xbl \
  --build-tree out/lemonades/mu-audit-build \
  --output out/lemonades/protocol-audit/after-xbl.json
python3 tools/lemonades/protocol_audit.py out/lemonades/artifacts/audit-xbl_lp5 \
  --build-tree out/lemonades/mu-audit-build-lp5 \
  --output out/lemonades/protocol-audit/after-xbl_lp5.json
out/lemonades/mu-venv/bin/python tools/lemonades/inspect-usb-abi.py \
  out/lemonades/stock/LE2101_14.0.0.2301 --output out/lemonades/protocol-audit/usb-abi.json
python3 tools/lemonades/check-framebuffer.py
python3 -m unittest discover -s tools/lemonades -p 'test_*.py'
python3 tools/lemonades/qemu-smoke.py
```

完整构建沿用 [构建步骤](LEMONADES-UEFI-BUILD.md)，先运行 `common/build.sh lemonades`，
再用新的 overlay/build/artifact 目录重新生成并暂存输入。本轮目录为
`uefi-audit-overlay` / `mu-audit-build` 和 `uefi-audit-lp5-overlay` / `mu-audit-build-lp5`。
42 项项目测试通过；两套 BaseTools 各 309 项测试通过，另有 framebuffer sanitizer 测试和
QEMU EFI 执行检查。全程没有连接、解锁、刷写手机。

## 仍未解决的初始化问题

1. **协议安装结果**：尤其 EnvDxe、UFSDxe、PILProxyDxe、UsbfnDwc3Dxe 的强制初始化。
   不应通过安装空协议对象或统一改 TRUE 来掩盖依赖问题。
2. **Qualcomm HOB / Shim ABI**：Mu 提供 UEFI Config Lib 和 SerialPort Lib；多项厂商驱动
   包含这些名称。但这不证明所有调用与版本都兼容。`GetXblHobAddresses` 需要名为
   FD Reserved 的区域，当前 9R 内存图没有该项，因此此路径不会恢复 Scheduler/DTB Extension
   地址。后续需追踪实际使用这些 HOB 的厂商路径，不能凭空补一个内存地址。
3. **页面池及保留区**：`SecPagePoolCount` 仍为 Mu 模板值；未在扫描的原厂 PE 中找到这个
   字符串，但未排除 SEC/TE 或间接访问，因此没有贸然同步数值。IPC SHM/HYP 也仍待验证。
4. **硬件操作**：Kona SEC 仍执行 watchdog MMIO 与 MDP SMMU detach；驱动连接还会触发
   存储、充电、USB 初始化。这些行为没有经过设备测试。本轮的存在性查询不改变这一限制。

这些记录将下一阶段的审查集中到具体调用路径；当前产物仍是待验证 UEFI 诊断固件。
