# 对照 ios-topaz：一加 9R 尚缺哪些工作

审查日期：2026-10-25。参考 [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz/tree/e4772911e116ab4ab6c4ac1f38e6106fefe8b483)，
`topaz` 分支固定 commit `e4772911e116ab4ab6c4ac1f38e6106fefe8b483`。
源码已获取到 `out/lemonades/reference/ios-topaz`，审查文件摘要见
`tools/lemonades/ios-topaz-reference.json`。未执行参考项目的构建、刷写或恢复脚本。

结论：我们的已完成工作集中在 **9R 固件提取、候选 UEFI、诊断 EFI 和离线兼容性检查**。
离真正运行 iOS，主要还缺 **9R XNU 启动闭环、硬件驱动接入及用户空间集成**。
仓库已有 HackiOS 通用 XNU/GPU/网络/文件系统基础，不能重复算成“从零缺失”；
但拥有 redwood 源码也不能算作完成了 9R 适配。

后续实现已推进机型隔离、ADT/boot_args 合约、S3908 重组/队列适配和 QEMU 最小用户态基线，
新内核构建已打通，触摸初始化会话也已补齐，见 [最新会话实现](LEMONADES-TOUCH-SESSION.md)；早期阶段
详见 [离线内核与输入链路推进](LEMONADES-KERNEL-OFFLINE.md)。下文表格保留本次初始对照状态。

## 最值得调整的工作重点

### P0：启用内核之前，先隔离机型与外设

本地 `xnuloader/loader.c` 的 `platform_redwood` 和 `platform_lemonades` 都有
`io_base = 0x00400000`。但 `redwood_wifi.c` 的入口、`redwood_adreno.c` 的自动启动检查，
用 `pe_arm_get_soc_base_phys() == REDWOOD_SOC_BASE` 识别 redwood，常量恰好也是该地址。
这个判断不能区分两款手机。

`redwood_input_init()` 还会统一调用 CPU 调频、Goodix、按键、电池、UFS、GPU、Wi-Fi、ADSP 等入口。
其中多项已有 boot-arg 开关，不能描述为全部无条件访问硬件；但当前没有 9R 的能力表与统一隔离。
一旦将来开放 handoff 并带入 redwood 参数，地址相等不能阻止调用错误的芯片初始化路径。
当前 probe 明确拒绝 XNU handoff，因此这不是已经发生在手机上的故障。

参考项目的 [0080 补丁](https://github.com/MakrSas/ios-topaz/blob/e4772911e116ab4ab6c4ac1f38e6106fefe8b483/xnu/patches/0080-topaz-cpu-topology-skip-sweet-hw.patch)
先隔离旧机型的按键、触摸、USB，再逐项移植。这是我们应借鉴的实施顺序。
验收应是：9R 的未知外设默认不初始化，即使误带旧机型启动参数也不能通过机型检查。

### P0：引导路线需要比较，Qualcomm Scheduler 不是所有路线的前提

参考项目 [shim/start.S](https://github.com/MakrSas/ios-topaz/blob/e4772911e116ab4ab6c4ac1f38e6106fefe8b483/shim/start.S)、
[shim/loader.c](https://github.com/MakrSas/ios-topaz/blob/e4772911e116ab4ab6c4ac1f38e6106fefe8b483/shim/loader.c)
实现的是原厂 ABL → 裸机启动程序 → XNU。它不先启动完整的替代 UEFI/DXE 驱动栈。
本地候选路线是 ABL → BootShim → Mu SEC/DXE → 诊断 EFI；完整 XNU 交接尚未开放。

因此此前 Scheduler/HOB/Shim 的修复是 UEFI 路线上的真实进展，但 **不是 iOS 的通用必要前提**。
Qualcomm 固件 Scheduler 与 XNU 自身调度器也不是同一套服务。
应将“继续完整 UEFI”和“直接从 ABL 进入最小 XNU”作为两条可比较路线，不让所有后续工作都等待
原厂 Scheduler。前者可复用固件显示/USB等服务；后者减少 DXE 依赖，但需要自行处理早期异常、
显示日志、CPU/中断、缓存、内存和硬件接管，并可能失去现有固件服务与返回路径。

本次没有擅自切换路线。参考裸机代码中的地址、ABI 和 ABL 行为属于 topaz，不能直接移植为 9R 成品。

## 缺口清单

| 优先级／环节 | ios-topaz 中的源码依据 | 9R 当前状态 | 还要完成的验收 |
| --- | --- | --- | --- |
| P0 独立 XNU 平台与构建 | `xnu/patches`、`xnu.yml`、`build-local.sh` | 有 HackiOS kernel 基础；`common/build.sh lemonades` 在 probe 分支提前退出，没有构建 9R XNU | 明确机型配置、禁用错误外设；产出带来源和配置记录的 9R 内核 |
| P0 ADT、boot_args、payload | `mkadt.py`、`mkpayload.py`、`shim/loader.c` | 已有 loader 内的通用 Apple Device Tree 构造及 Mach-O 加载逻辑；9R 参数只是诊断用，handoff 被禁用 | 可独立验证的 9R ADT/boot_args、段和重定位检查、保留区排除、入口与返回契约 |
| P0 CPU 能力和启动环境 | `shim.c` 的 MMFR/PSCI/GIC/定时器诊断；0081、0140、0141 | EFI 已打印 MIDR/MMFR0/CNTFRQ；未建立每个目标核心的页大小、指令能力、EL、PSCI 和异常验证闭环 | 先单核，确认页大小和指令集，再验证 GIC、timer、PSCI；不能照搬 topaz 的 Gold-only / 4K 选择 |
| P0 内核级离线测试 | `qemu-sweet.py` 装载 XNU payload，采集异常、寄存器和屏幕结果 | 本地有上游 QEMU XNU/iOS 工具，但本轮 9R smoke 只运行 EFI | 建立 9R 平台数据及内核组件的 QEMU 测试；明确通用 virt 与 SM8250 的差别 |
| P1 实机早期日志与恢复 | `shim/console.c`、异常向量、persistent log、`sweet-crash.py`、`RECOVERY.md` | EFI 日志/截图/协议快照及候选镜像隔离已有；无 9R 内核崩溃回收和设备专属恢复验证 | 先 RAM/USB 或屏幕日志；记录 CPU、异常和启动阶段；实机备份/匹配后制定恢复步骤 |
| P1 显示接管 | 0092–0107、IOSurface、帧缓冲及缓存维护相关补丁 | GOP 诊断与 UEFI framebuffer 错误修复已做；已有通用 MiniIOSurface/MiniIOMobileFramebuffer，但没有 9R XNU 显示接管验证 | 确认 scanout 地址、stride、格式、DSI/DSC、SMMU、cache；先软件静态帧，再双缓冲与合成 |
| P1 触摸与按键 | FT5452 总线驱动、HID、0090/0950 等释放事件修正 | S3908 仅普通报文解析及宿主测试，未链接 XNU | GENI I²C、时钟/供电/reset/IRQ、TCM 配置及分包、输入事件和 release-all 路径 |
| P1 系统镜像与用户空间 | `mkiosroot.sh`、`sweet-root-tweaks.py`、userland 目录 | 当前 checkout 没有 `userland/` 和 `ios165/`；有上游导入/构建入口，但未完成 9R 集成 | 锁定兼容版本与身份/ADT；先用可回滚的内存镜像跑 init/launchd，再到 backboardd/SpringBoard |
| P1/P2 存储 | UFS driver、GPT/LUN、HFS+ 根挂载和日志 | 原厂 UFSDxe 静态包含；上游有 APFS 和 redwood UFS 驱动，未适配 9R | 分清 UEFI Block I/O 与 XNU 直接驱动；验证 DMA、cache、LUN/GPT、只读访问，再讨论写入 |
| P2 GPU | Adreno 610 驱动、GMU/SMMU、Mesa bridge | 本地已有 Adreno 642L 和 Mesa 相关接口基础；9R Adreno 650 尚未适配 | 固件、clocks/rails、GMU、TZ、IOMMU、命令提交、surface/cache/同步，不能只换芯片名 |
| P2 网络与音频 | Modem PAS、GLINK/QRTR/QMI/WLFW、WLAN、ADSP/音频补丁 | 上游已有同类基础；未确认 9R 实际子系统固件与接入路径 | 逐项建立硬件身份/服务依赖，完成固件启动、数据面、iOS 桥接和实机证据 |
| P2 电源、充电、RTC、休眠 | 电池/charger/display sleep 补丁，部分 RTC 仍列为待办 | 9R 仅固件层初始化审查，未完成这些 XNU 服务 | PMIC/SPMI、温度/电量/充电策略、显示电源、休眠唤醒、时钟来源 |

Linux DTB/DTBO 与 Apple Device Tree 是不同格式。我们已有设备树提取与合并，并不等于已经得到
可启动 XNU 的 ADT；同样，UEFI 上 USB/GOP 可用也不等于 XNU 的驱动和 iOS 服务已可用。

## 可以借鉴，但不要照搬

- **方法和测试优先复用**：最小单核启动、逐外设开关、异常解码、启动里程碑、cache/DMA 验证、
  独立 payload/ADT 检查及 panic 判定。
- **同源代码先比较差异**：其 [CREDITS](https://github.com/MakrSas/ios-topaz/blob/e4772911e116ab4ab6c4ac1f38e6106fefe8b483/CREDITS.md)
  明确多项 GPU/显示/音频/网络工作源于 HackiOS。我们已有部分祖先组件，不应直接叠加整套补丁，
  应逐项确认修复适用的源版本、接口和许可证标注。
- **boot v4 不是通用升级**：它的 [build.sh](https://github.com/MakrSas/ios-topaz/blob/e4772911e116ab4ab6c4ac1f38e6106fefe8b483/shim/build.sh)
  针对 topaz ABL，将 payload 放到 Image 尾部。9R 当前有原厂/LineageOS 的 boot v2 依据，
  不应因为参考项目用 v4 就改成 v4。
- **CPU 方案不照搬**：topaz 有 A53/A73、16K 限制及可选 4K/AMP 补丁；9R 必须根据自身核心
  能力判定。现有代码读取一个核心的 MMFR0，不足以证明所有核心的能力。
- **存储布局不照搬**：参考项目的 HFS+ userdata 和恢复脚本绑定其分区布局；本地已有 APFS 路线。
  没有必要为跟随参考项目改文件系统，更不能照搬其 userdata/GPT 操作。

## 参考项目自身的证据限制

首页同时出现八核/音频已加入的描述，以及旧的“四核、无音频”状态。
仓库确实有 `0140-topaz-4k-pages.patch`、`0141-topaz-amp-clusters.patch` 和音频补丁；
但默认 `mkadt.py` 仍构造四核树。存在补丁不等于当前默认构建组合、提交和设备日志已对应验证。
本次只审查源代码，不把作者叙述转写成我们独立验证过的硬件事实。

## 后续可离线完成的顺序

1. 建立明确的 XNU 平台身份与外设允许表，解决共享 SoC 基址无法识别机型的问题。
2. 把 9R 的 ADT/boot_args/内存布局生成与校验从实际启动分离，覆盖越界、重叠、页对齐和身份来源。
3. 形成独立的 9R 最小 XNU 构建配置及 QEMU 内核级检查，先以最小 init/诊断程序验收。
4. 对裸机 ABL 路线做离线原型/可行性比较；保留现有 UEFI 诊断路径用于实机证据采集。
5. 获取并固定匹配的 userland 源码和构建依赖，建立用户空间集成测试；外设按显示、触摸、存储等顺序推进。

这次增加的是源码对照和工作缺口记录，没有解除现有 probe 限制、移植整套 topaz 补丁或更改启动路线。
