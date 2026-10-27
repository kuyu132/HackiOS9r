# 一加 9R / lemonades 移植记录

最新诊断能力：[启动日志保留、故障快照与电脑端采集](LEMONADES-LOGGING.md)。

最新身份修复与主屏对照：[设备/事件声明一致性及显式模拟主屏路径](LEMONADES-HID-PROFILE.md)。

后续恢复与效率修复：[HID 服务端重启验证及事件驱动输入等待](LEMONADES-HID-RECOVERY.md)。

最新常驻服务进展：[触控桥接、进程重启恢复与主屏接入条件](LEMONADES-TOUCH-BRIDGE.md)。

状态：**离线 bring-up 第一阶段，尚未在 9R 上启动 UEFI、XNU 或 iOS。**
当前产物包括 UEFI 诊断程序、两套候选 UEFI FD、XNU 平台隔离和触摸源码组件，以及离线启动合约测试，不是可以刷入的 iOS ROM。
长期目标与验收阶段：[持续开发目标](LEMONADES-DEVELOPMENT-GOAL.md)。最新用户态进展：[Mach IPC 与系统组件导入](LEMONADES-MACH-USERLAND.md)。硬件侧最新进展：[触控平台映射与资源生命周期](LEMONADES-TOUCH-PLATFORM.md)。前一阶段：[GENI FIFO 传输与触摸工作线程接口](LEMONADES-GENI-TRANSPORT.md)、[S3908 初始化会话](LEMONADES-TOUCH-SESSION.md)。构建基础：[原生新内核构建与 QEMU 验证](LEMONADES-NATIVE-KERNEL.md)。前一轮记录见 [离线内核与输入链路推进](LEMONADES-KERNEL-OFFLINE.md)。
开发分支：`port/oneplus-9r`。记录日期：2026-10-26。

## 已实现与验证范围

| 内容 | 状态 |
| --- | --- |
| 独立 `lemonades` 设备配置及编译入口 | 已实现 |
| AArch64 EFI 诊断程序 `out/lemonades/loader.efi` | 本机交叉编译通过 |
| QEMU 中运行该 EFI，获取 CPU、GOP 和内存图 | 通过；日志在 `out/lemonades/qemu-probe.log` |
| USB 日志/内存图/截图协议 | 复用上游 Qualcomm UEFI 协议，限制为诊断命令；没有实机验证 |
| SM8250 v2.1 基础 DTB + 9R overlay | 从固定版本公开内核源码编译、合并通过 |
| 候选 9R Mu-Silicium 平台工程 | 普通 / LP5 两套均完成完整 FD 构建与拆包核验；未实机启动 |
| 专用 `ProbeBootManagerLib` | 真实 Mu 头文件编译及完整固件链接通过；最终 BDS 内容已核对 |
| 候选地址的 BootShim | 编译通过，附带地址与哈希元数据；尚未实机验证 |
| LineageOS 9R / SM8250 设备配置导入 | 固定版本，生成启动参数与带来源的固件清单 |
| 9R 镜像布局 | header v2 / 4096-byte page / base=0 / 独立 DTB 段；字节级检查通过 |
| 原厂 XBL / XBL config / boot / DTBO 等 | 已从 LE2101_14.0.0.2301 CDN 包提取 16 个分区，分区 SHA-256 校验通过 |
| 原厂设备树 | 拆分 22 棵 DTB 和 19 个 DTBO；合并三个 9R SoC 修订版候选 |
| 镜像/固件/运行入口和内核集成回归测试 | 121 项宿主回归通过；QEMU 桌面服务和外部配置刷新问题仍待解决（宿主通过不代表全部运行时兼容） |
| S3908 解码、续读重组、触点状态与 XNU 队列适配源码 | 宿主 ASan/UBSan、10 万次解码变异和 AArch64 便携组件编译通过；已进入新内核编译与链接；总线/实机接入未完成 |
| S3908 初始化协商、命令分包与响应分发 | 4,940 组分包组合、超时/复位/迟到响应和 XNU 队列组合测试通过；已连接 GENI 后端，尚无实机 I/O |
| GENI FIFO → TCM 会话 → XNU 输入队列 | 448 组 FIFO 组合及 7 种 FIFO 深度端到端模型通过；资源准备与自动调度未接入 |
| XNU 触控平台映射与清理 | 已实现 device-memory 映射、GPIO 采样、GCC/TLMM 预检及异步退出；sanitizer 与完整内核编译通过；仍需外部资源提供者，无实机验收 |
| XNU 硬件身份隔离 | loader 明确 board 属性；旧机型与 virtio 初始化能力检查已加入并通过宿主测试 |
| 独立 ADT/boot_args 测试产物 | 对齐/保留区/重叠等校验、Apple arm64 ABI 逐字节对比通过；合成输入，不可启动 |
| 通用 XNU → 最小进程 1 的 QEMU 测试 | 新编译内核通过；携带旧机型硬件参数也通过，非实机测试 |
| 静态用户态进程/VM/IPC 基础 | QEMU 实际执行 fork/pipe/wait4、匿名映射、mprotect 调用及 COW 隔离；尚非动态链接或 Mach IPC/launchd 验证 |
| Mach 队列与内核 MIG RPC | mach_msg2 请求/回复、send-once、65 轮端口生命周期及 task_info 通过；不是跨任务 bootstrap/launchd 验证 |
| iOS 16.5 用户态输入 | 固定 Apple CDN/BuildManifest；App/OS cryptex 和 rootfs 已下载校验，dyld/launchd/缓存已只读提取 |
| APFS 与动态用户态 | [APFS → 诊断 PID 1 → Apple dyld → libSystem](LEMONADES-DYNAMIC-USERLAND.md) 在 QEMU 通过；无实机性能结论 |
| 原厂 launchd 与 bootstrap | [原厂 launchd/xpcproxy 启动一个测试服务并完成注册/查询](LEMONADES-LAUNCHD-BOOTSTRAP.md) 通过；RAM 根盘恢复环境，完整服务、persona 和桌面未完成 |
| Persona 与服务凭证 | [恢复 XNU persona 校验](LEMONADES-PERSONA.md)，新内核验证实际 UID/GID、无权限请求拒绝；原厂 --init 已执行并创建 persona，[用户会话集成和限制](LEMONADES-USERMANAGER.md) |
| 原厂基础服务 | logd/notifyd/logd_helper 实际启动；跨进程通知和状态、[muser RPC](LEMONADES-MUSER-XPC.md)、[主 NSXPC 端点的权限拒绝与前台会话读取](LEMONADES-NSXPC.md) 通过；完整用户会话生命周期、日志业务仍未验证 |
| 原厂桌面服务 | [backboardd 日志权限修正及容器服务接入](LEMONADES-BACKBOARD.md)；[ICU 数据修复日期初始化](LEMONADES-ICU.md)，[原厂事件配置接入后记录 startup complete](LEMONADES-BACKBOARD-CONFIG.md)；[HID 查找与属性 RPC 可用但服务枚举仍空](LEMONADES-HID-CLIENT.md)，显示/迁移未完成，SpringBoard 未启动 |
| 触控到 HID 的离线事件层 | [事务式多指状态与原厂 IOKit 字段读回通过](LEMONADES-HID-TOUCH.md)；合成服务注册/事件接收/移除对照通过，但主屏明确忽略外部虚拟触控；常驻桥接与实机未验 |
| 输入丢帧与恢复 | [独占完整快照队列、非阻塞/中断/copyout 恢复及队列到 HID 的丢帧恢复](LEMONADES-INPUT-QUEUE.md) 已通过真实 QEMU 字符设备与原厂 HID 对照；常驻服务、主屏与实机未验 |
| 会话状态与偏好设置 | [会话 RPC / 保存记录 / 内核 UID 三方一致；原厂 cfprefsd 与独立进程配置读写删除通过](LEMONADES-PREFERENCES.md)；[root/mobile 同域读写隔离、实际消息发送者身份通过](LEMONADES-AUDIT-MOBILE.md)；持久化和应用沙箱隔离未验 |
| 文件事件与缓存 | [原厂文件创建回调通过](LEMONADES-FSEVENTS.md)，[CFTypes / IgnoreSelf 跨进程目录删除回调通过](LEMONADES-PREFERENCES-LISTENER.md)；[API 跨进程更新和 vnode 通知通过](LEMONADES-PREFERENCES-REFRESH.md)，直接文件替换后旧、新客户端均读旧值，完整集成仍未通过 |
| RAMFS 原子保存 | [rename swap/excl、目录边界与并发读取实测通过](LEMONADES-RAMFS.md)，原厂文件保存的 5 个 persona ID 与内核一致；仍为易失数据卷，不提供 UFS 持久化 |
| 包含新增代码的 XNU 最小配置构建 | 原生 macOS 构建、完整导出检查通过；精简 IIG 和 Apple DART/PPL 等能力限制见构建文档 |
| 协议依赖及初始化首轮审查 | 已修正 3 项悬空 APRIORI、USB ABI 检查和 framebuffer 错误路径；42 项协议存在性日志已加入 |
| Qualcomm HOB 路径及兼容性修复 | 已追踪原厂 SEC/EnvDxe，修复 FV 越界和锁清理、配置字符串与 Shim 失败输出；两套 FD 重建核验通过 |
| Shim 注册及版本兼容 | 已补齐有容量限制的注册和版本选择；两套原厂函数共 2,270 次差分操作及边界 sanitizer 检查通过 |
| XNU 启动、触屏、GPU、Wi-Fi、充电、蜂窝网络 | 尚未适配验证 |

原有 EFI smoke 使用 Cortex-A72 和通用 UEFI，验证 EFI 入口、重定位、平台选择、诊断和退出路径。
kernel smoke 使用 Cortex-A76，分别保存预编译基线与新编译内核到进程 1 的报告；不能与实机验证混用。
它没有模拟 SM8250、9R 屏幕或 Qualcomm USB 协议，不能证明手机能启动。
测试脚本会删除旧串口日志后启动新的 QEMU，并记录被测 EFI 的 SHA-256。

## 源码依据

版本锁定在 `tools/lemonades/sources.json`：

- [HackiOS kernel](https://github.com/oosexgang/hackios-xnu-kernel/tree/d82c64a3a31cd27a0a0afbf6e213e467e44b1b4c)：移植起点。
- [Mu-Silicium](https://github.com/Project-Silicium/Mu-Silicium/tree/4cba43c90e02cdbefbcd9fcdbda33d2328deaec0)：`kebabPkg` / `KonaPkg` 参考。`lemonadePkg` 是另一种 SoC 的一加 9，不能当作 9R。
- [LineageOS SM8250 kernel](https://github.com/LineageOS/android_kernel_oneplus_sm8250/tree/98a7970af93b7e01ee77156e7fa0eb7e059a57f0)：`arch/arm64/boot/dts/vendor/oplus/lemonades/` 和 `qcom/kona.dtsi`。
- [LineageOS 9R device](https://github.com/LineageOS/android_device_oneplus_lemonades/tree/d137be73a7d60aba45e5763764a06ea446940808)：设备配置、board-info、专用文件提取清单。
- [LineageOS SM8250 common](https://github.com/LineageOS/android_device_oneplus_sm8250-common/tree/9883c00ec5893022f1e2a569788c9cef0263bcdb)：`BoardConfigCommon.mk`、共享固件清单。

`tools/lemonades/lineage.py` 从固定 commit 读取资料，不执行 Android makefile。
启动参数写入 `common/devices/lemonades-boot.json`，由镜像打包器和 UEFI 工程生成器共同读取。
`out/lemonades/lineage-reference.json` 保存内核配置、board-info 及固件来源：
9R 专用清单注明 `LE2101_14.0.0.2301(EX01)`，共享清单注明 **8T** 的
`KB2005_14.0.0.603(EX01)`（清单中另行注明的条目除外）。其中包括项目 20828 的 S3908
固件名和 Adreno 650 固件名。随后已取得该印度版原厂包的 XBL 等分区，
本轮未提取 vendor/odm 中的 GPU/触屏固件，也没有混用其他手机二进制。

下载来源、哈希、内存图修正和驱动暂存详见 [原厂固件离线适配记录](LEMONADES-STOCK-FIRMWARE.md)。
首次完整构建记录见 [UEFI 构建记录](LEMONADES-UEFI-BUILD.md)。
启动清单修正、USB ABI 和 framebuffer 检查见 [协议与初始化审查](LEMONADES-PROTOCOL-AUDIT.md)。

Scheduler/ Shim 路径及内存错误修复见 [Qualcomm HOB 审查](LEMONADES-HOB-AUDIT.md)。

最新候选固件和 Shim 注册/版本选择、原厂函数仿真比对见 [Shim 兼容记录](LEMONADES-SHIM-COMPAT.md)。

LineageOS 的 Linux 驱动可提供硬件协议与初始化顺序的依据；其内核 API、Android HAL 和
闭源库不能直接作为 XNU/iOS 驱动加载。当前已据此独立实现 [S3908 报文解析](LEMONADES-S3908.md)。

从公开设备树得到的初始硬件信息（仍需与具体手机/系统版本核对）：

| 项目 | 证据 |
| --- | --- |
| CPU 编号 | `cpu@0` … `cpu@700`，MPIDR Aff1，8 核；低容量核为 0–3 |
| GICv3 | distributor `0x17A00000`，redistributors `0x17A60000`，stride `0x20000` |
| 触屏 | Synaptics S3908，`qupv3_se13_i2c`，控制器 `0xA94000`，I²C 地址 `0x4B` |
| 触屏 GPIO | IRQ 39、reset 38；坐标 1080×2400 |
| overlay 标识 | `qcom,board-id = <0x10008 0>`，`oplus,dtsi_no = <20828>` |
| 显示保留内存 | `0x9C000000` 起，splash 大小 `0x02300000`，其后为 DFPS 保留区 |

完整证据（包括 reserved-memory、SoC ID 和文件哈希）在生成的
`out/lemonades/hardware-reference.json`。overlay 的板号/项目号并不是唯一硬件身份证明；
编译的 v2.1 变体也不是从用户手机提取的 DTB。

## 构建与检查

工具：Python 3、Bash、Git、Clang、`lld-link`、`llvm-objcopy`、dtc（含 `fdtoverlay` / `fdtget`）。
QEMU 测试另需 `qemu-system-aarch64` 和 AArch64 UEFI 固件。
本机为 Apple Silicon macOS，构建这些离线产物不需要下载 Apple IPSW。

```sh
common/build.sh lemonades
python3 tools/lemonades/lineage.py
python3 tools/lemonades/build-reference-dtb.py
python3 tools/lemonades/inspect-dtb.py \
  out/lemonades/reference-dtb/lemonades-reference.dtb \
  --output out/lemonades/hardware-reference.json
python3 tools/lemonades/build-shim.py
python3 tools/lemonades/prepare-uefi.py --output out/lemonades/uefi-lineage-overlay
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py' -v
bash tools/lemonades/check-touch.sh
python3 tools/lemonades/qemu-smoke.py
```

`prepare-uefi.py` 拒绝覆盖已有目录；再次生成时用 `--output` 指定新的目录。
默认输出 `out/lemonades/uefi-overlay/`，可供审查；它不会修改参考 Mu-Silicium checkout。
本次含 LineageOS 参数的新版工程位于 `out/lemonades/uefi-lineage-overlay/`；旧输出不会自动更新。
最新含原厂内存图和驱动暂存的工程是 `out/lemonades/uefi-stock-overlay/` 与
`out/lemonades/uefi-stock-lp5-overlay/`；生成/填充流程见原厂固件记录。
其他机器可给 QEMU 脚本传入 `--firmware /path/to/AAVMF_CODE.fd`，给 shim 脚本指定 `--objcopy`。

单独复现 UEFI 启动管理代码的接口编译检查：

```sh
git -C Mu-Silicium submodule update --init --depth 1 Mu_Basecore Common/Mu
bash tools/lemonades/check-uefi-interface.sh
```

本次在本机安装了 Homebrew `lld`，其依赖安装同时升级了 LLVM、xz 和 z3。

参考源码目录：

- `Mu-Silicium/`：上面固定的 Mu-Silicium commit，无需拉全部子模块即可生成候选工程和 shim。
- `sources/kernel-sm8250/`：上面固定的 kernel commit。稀疏 checkout 至少包含
  `arch/arm64/boot/dts/vendor/qcom`、`arch/arm64/boot/dts/vendor/oplus`、
  `include/dt-bindings`、`include/uapi`。少了 `include/uapi` 会缺少 input event 的间接头文件。
- `sources/device-lemonades/`、`sources/device-sm8250-common/`：上面固定的两个 LineageOS 设备仓库。
  当前均取自 `lineage-24.0`；复现以 commit 为准，不跟随分支最新状态。

dtc 对上游 DTS 产生的警告保存在 `out/lemonades/reference-dtb/*.warnings.log`。
overlay 独立编译时的部分 cell 格式警告源于父节点位于基础 DTB；当前没有把“编译成功”当作硬件验证。

## 引导隔离

`LOADER_TARGET=lemonades` 使用明确的编译目标，保留 UEFI 报告的 GOP，
不按 framebuffer 地址猜机型，也不访问 QEMU 的 `fw_cfg` 寄存器。
诊断构建会拒绝 XNU handoff、payload 上传、ramdisk、watchdog 测试等命令；
不读取固定的 `0xF0000000` payload 区，不调用 POCO 原始 `logdump` 写入路径。
允许的 USB 命令只有 `getvar:*`、`upload`、`oem log`、`oem memmap`、`oem screenshot`、`reboot`。
这描述的是我们的 EFI 程序，不能据此保证尚未审查的厂商 UEFI 驱动没有写入行为。

`common/run.sh lemonades` 和 `DEVICE=lemonades ./xl enter` 会在触及 USB 前停止。
旧的裸 `./xl` 仍是上游的 **redwood 专用工具**，不要用于 9R。

候选 UEFI 将诊断 EFI 嵌入 firmware volume，由独立 `ProbeBootManagerLib` 启动，
不沿用上游的 XNUP 固定地址 payload、8T ACPI 表或 POCO 的日志分区入口。
该库返回后停止，不继续自动寻找其他系统。

`mkxnuimg.py` 对非 redwood 目标要求显式的 `UEFI_FD`、`DTB`、`BOOT_SHIM`、
`FD_BASE`、`FD_SIZE`，并核对 shim 的 target、地址、SHA-256 元数据与实际 ARM64 镜像头。
缺少输入时不能回退到 POCO 文件；非 redwood 的 XNU payload 当前明确禁用。
测试中的启动镜像只使用临时目录，不作为发布产物保留。

9R 打包采用 LineageOS 的 header v2、4096 字节页、base=0 和独立 DTB 段，
并检查镜像不超过 96 MiB 的 boot 分区大小。DTBO 保持独立，不将 DTBO 分区拼接成 DTB。
候选 UEFI 的 kernel 段仍为 `gzip(BootShim + FD)`，未复制 Android 的内核命令行或 ramdisk。
未在设备配置显式指定的 offsets 沿用仓库内 mkbootimg 默认值；这些是 boot header 元数据，
不能据此把 `base=0` 解释为 UEFI 在物理地址 0 执行，或认为候选 FD 地址已得到验证。

生成工程同时包含修正后的 `build_uefi.py`：传递 `pagesize`，并保留有效的零值 `base`。
该脚本来自固定 Mu commit，仅修改上述两处；应用 overlay 时需要一同使用。
测试执行了其中真实的打包函数，检查最终命令行；完整 UEFI FD 已通过独立构建入口完成，
仍未选择实机 DTB 或生成默认 boot 镜像。

## 完成手机启动前的缺口

新增 [ios-topaz 源码对照与优先级](LEMONADES-TOPAZ-GAP-REVIEW.md)：重点是 XNU 平台隔离、ADT/内核级测试和直接 ABL 引导路线比较。

1. **固件与实际设备匹配**：已取得印度版原厂固件并分别准备普通 XBL / LP5 输入，
   仍需确认用户手机地区、内存类型及 SoC 修订号。候选工程暂存了 73/80 项引用；
   7 项缺失均处在当前关闭的自定义显示分支，80 条也包含注释/条件分支，不能当作必需驱动数量。
2. **UEFI 内存布局核对**：原厂 XBL 确认 FD `0x9FC00000` / 3 MiB，已修正 TZ/PIL、DXE 堆、
   ramoops 等区域。IPC SHM/HYP reservation 和 SecPagePoolCount 仍待初始化审查；
   还需核对实机 UEFI memory map，不能从静态配置直接宣布启动安全。
3. **UEFI 驱动审查**：两套 FD 已完成构建及内容核验，但仍需定位必要的 9R 专用兼容补丁、
   完成剩余协议提供者及连接驱动、USB、NVRAM、存储/充电初始化行为审查。
   首轮已核对 42 项 DEPEX GUID、修正 APRIORI 和 framebuffer，并确认 USB Device 静态 ABI。
4. **实机 stage 0**：在匹配且可恢复的测试设备上验证 UEFI 显示、USB 日志、GOP 格式和内存图。
   没有这一步，不能把候选 boot image 标为可用。
5. **XNU stage 1**：核对 16 KiB 页支持、中断与定时器、单核启动、独立内存窗口及返回路径；
   禁用/隔离 redwood 外设初始化后，再启用内核测试。当前没有改造 XNU 外设驱动。
6. **外设与用户空间**：S3908 普通报文解析已实现，仍需总线/供电/复位、TCM 分包重组、
   report config 确认和 XNU 输入事件接入，再做 GPU、网络、音频、充电等。
   S3908 不能用上游 Goodix SPI 驱动替代；App Store、Apple ID、蜂窝网络也不是启动桌面后自动获得。

手机目前未连接，以上实机验证均未执行，也没有刷写、解锁或修改手机分区。
