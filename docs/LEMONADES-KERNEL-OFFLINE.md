# 9R 离线内核与输入链路推进

日期：2026-10-25。本轮是 `LEMONADES-TOPAZ-GAP-REVIEW.md` 的后续实现。
**以下保留前一轮状态。后续已补齐原生依赖并成功构建/运行包含新增模块的最小通用 XNU，
见 [原生新内核构建与 QEMU 验证](LEMONADES-NATIVE-KERNEL.md)。仍无可刷写的 iOS ROM。**

## 已落地

### 明确硬件身份与访问范围

loader 在 `/chosen/hackios,board` 写入 `redwood`、`lemonades` 或 `qemu-virt`。
XNU 的 `pexpert/hackios_platform.h` 按完整属性长度和末尾 NUL 匹配，不读取 boot-arg，
不再用共享的 `0x00400000` 基址授予硬件访问权限。

- redwood 的 12 个初始化入口，以及 UFS 原生探测、speaker prepare、sound/mic DSP up、
  Linux Wi-Fi start/prepare，都先检查 redwood 能力，才解析参数、创建硬件线程或访问寄存器。
- 四个 virtio MMIO 初始化入口仅允许 `qemu-virt`，避免将 QEMU 地址应用到真机。
- `lemonades` 和未知身份目前没有这些能力；这不代表缺失的驱动已经实现。
- **兼容性变化**：旧 loader 不携带该属性时，以上外设默认关闭。更新内核时须配套更新 loader。
  Apple 用户空间身份、`platform-name` 和 `arm-io` 的基址不再具有授予这些能力的作用。

该策略是硬件兼容性边界，不是针对恶意 loader 的安全认证机制。默认通用 loader 仍保留上游的
GOP 地址平台选择方式；本轮没有把它升级为可靠的物理机型识别。9R 继续只使用显式 lemonades probe 目标。
宿主测试编译实际策略头文件，仅替换 DT 服务；覆盖缺失、长度错误、截断、额外尾字节和未知能力。
结构测试另外检查初始化入口在副作用之前执行该检查。

### ADT 与 arm64 boot_args 合约

`tools/lemonades/boot_contract.py` 生成独立 Apple Device Tree 硬件片段和 736 字节 boot_args，
与 Linux DTB/DTBO 分开。校验覆盖：64 位地址溢出、16K 对齐、重复/缺失分配、重叠、越界、
整段 XNU RAM 窗口与原厂保留区冲突、单核 MPIDR 候选范围及禁止外设启动参数。
ADT 另用有深度/计数/边界限制的解析器回读，并检查全部截断位置。

`common/lemonades/boot-contract-fixture.json` 中的 RAM 地址、分配大小、CNTFRQ 是**合成测试输入**，
不表示已测得的空闲内存或时钟。生成物标记 `bootable: false`，不送入现有启动镜像打包器。
它没有真实 Mach-O 段布局/重定位、运行时内存图、iPhone 用户空间完整身份、熵、显示交接或返回契约，
因此**不是可启动的完整 ADT/payload**。

`check-boot-abi.py` 从 Apple 固定 commit `c54f35ca767986246321eb901baf8f5ff7923f6a` 读取
arm64 结构声明，编译后与 Python 生成物逐字节对比；全部 736 字节一致。
loader 也增加了对应的结构大小/字段偏移编译断言。

### S3908 从报文到输入队列

`common/lemonades/` 新增：

- `s3908_tcm`：普通触摸报告的 bounded continued-read 重组，验证 `A5 03` 前缀；
  丢弃 predictive-read 尾部，处理 Linux 中最后一字节 padding 不再读取的行为，并显式记录
  `synthesized_padding`，不把合成 padding 当作实机采样。它不是通用命令/响应分发器。
- `s3908_input`：维护触点集合，生成 down/move/up，将经确认的坐标点数映射至 0–65535；
  空帧/显式 lift 释放旧触点，复位/已确认传输超时可显式 release-all。
  坏包/越界坐标不会产生事件，也不修改原有状态。
- `xnu/files/bsd/dev/lemonades_touch.c`：将上述事件交给现有 `redwood_touch_post`。
  仅接受 lemonades 身份，要求输入队列已初始化，且由单个串行工作线程调用。

`xnu/apply.sh` 把便携源代码复制到 XNU 构建树，`bsd/conf/files` 已注册解码、状态、重组和适配器。
`xnu/export.sh` 排除这些生成的副本；如果有人改了副本而没有同步 `common/lemonades`，会拒绝导出以防丢失修改。
宿主测试编译实际适配器，仅 mock DT 和输入队列；不是完整内核链接/实机测试。

GENI I²C、供电/时钟/reset/IRQ、异步响应分发、配置回读、坐标方向、休眠恢复仍待实现和验证。
目前没有任何代码自动启动控制器。

### XNU 到进程 1 的 QEMU 基线

已固定 userland 源码 commit：`a79ff0772a3454fd1ef127e181e5b3bce6c9ce18`，来源和关键文件哈希在
`tools/lemonades/userland-lock.json`。源码位于 `out/lemonades/reference/hackios-xnu-userland`，
没有把整个项目覆盖到主工作区，也没有下载或构建完整 iOS 系统镜像。

`kernel-smoke.py` 使用新编译的通用 loader、新编译的上游无 libc 静态 `hello`、仓库预编译 XNU，
在 QEMU virt / Cortex-A76 / GICv3 / 单核上完成：

```text
platform qemu-virt
Darwin Kernel Version 22.5.0
Hello from user space on Darwin!
I am process 1, uid 0, console fd 0.
```

上游 `hello` 特意退出进程 1，所以随后出现 initproc panic 是这个测试的预期终止。
脚本要求里程碑顺序正确，只接受该 panic，其他 panic 或缺失标记均失败。
每次删除旧日志并记录 kernel、loader、hello、payload 和日志哈希。
结果：`out/lemonades/kernel-smoke/result.json`，`passed: true`。

**预编译 XNU 不包含本轮机型检查/触摸适配代码。** 该测试证明通用内核/用户态基线，
不能证明新内核修改已在 QEMU 执行，也不能证明 SM8250、9R 或 SpringBoard 可用。

## 完整内核构建的实际结果

本轮已生成应用完整补丁和新增源码的树：`out/lemonades/xnu-integrated-src`。
完整补丁反向 dry-run 检查通过。修复了原先只用 `nproc` 和 `/proc/meminfo` 的宿主检测，
在 Darwin 使用 `sysctl`，Linux 保留原路径。

使用本机 Xcode 26.6 / iPhoneOS26.5 SDK 运行完整 make 后，已通过原先内存检测错误，
构建 setup 工具后停在缺少 `usr/local/libexec/availability.pl`。
日志：`out/lemonades/xnu-integrated-native.log`。构建退出码非零，**没有产出新内核**。

后续必须补齐并固定 XNU 8796 对应的 SDK 补充层、AvailabilityVersions、libdispatch/firehose、
libpthread 和匹配 IORPC ABI 的 IIG 生成方案。已有 Linux `xnu-deps/setup.sh` 描述这些依赖，
但不能直接把其 Linux 工具链和文件操作当作 macOS 原生构建支持。
参考 topaz 使用 Xcode 15.4 / KDK 13.5；本机只有 Xcode.app，未安装该工具链。
不能用预编译文件替代一次失败的构建验收。

## 复现

```sh
bash tools/lemonades/check-platform.sh
bash tools/lemonades/check-touch.sh
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'
python3 tools/lemonades/boot_contract.py --output out/lemonades/boot-contract-new
python3 tools/lemonades/check-boot-abi.py --source out/lemonades/xnu-integrated-src
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/kernel-smoke.py
```

`boot-contract.py` 只接受新的输出目录，避免覆盖来源记录；QEMU 脚本依赖 macOS xcrun、
QEMU AArch64、EFI firmware 和锁定的 userland 源码。默认固件路径是 Homebrew 的路径，可用 `--firmware` 覆盖。

## 仍未完成的范围

完整新 XNU 构建、9R 真实 ADT/payload 和 CPU/EL/PSCI 交接，直接 ABL 裸机路线，
显示接管和 panic 回收，触摸总线/按键、UFS/DMA、A650 GPU、Wi-Fi/蜂窝、音频、PMIC/充电/休眠，
以及完整 iOS init/launchd/backboardd/SpringBoard 集成，均不能列为完成。
其中有继续离线开发的空间；寄存器时序、内存所有权、启动恢复和设备功能验收最终需要实机。
现有 9R probe/handoff 限制继续保留，本轮未改写之前的候选 FD，也未执行刷写。
