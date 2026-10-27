# 一加 9R 完整 iOS 适配的持续开发目标

最新诊断能力：[启动日志保留、故障快照与电脑端采集](LEMONADES-LOGGING.md)。

最新身份修复与主屏对照：[设备/事件声明一致性及显式模拟主屏路径](LEMONADES-HID-PROFILE.md)。

后续恢复与效率修复：[HID 服务端重启验证及事件驱动输入等待](LEMONADES-HID-RECOVERY.md)。

最新常驻服务进展：[触控桥接、进程重启恢复与主屏接入条件](LEMONADES-TOUCH-BRIDGE.md)。

建立日期：2026-10-26。用户目标：在 OnePlus 9R（lemonades）实机上流畅运行 iOS，所有功能正常。
后续进展见 [Mach IPC 与系统组件导入](LEMONADES-MACH-USERLAND.md) 和
[APFS 与动态用户态集成](LEMONADES-DYNAMIC-USERLAND.md)；本文末尾的 70 项为前一轮历史结果。
最新进展见 [原厂 launchd 与 bootstrap 集成](LEMONADES-LAUNCHD-BOOTSTRAP.md)。
当前内核与身份验证进展见 [Persona 初始化与进程身份](LEMONADES-PERSONA.md)。
后续原厂 usermanagerd/logd/notifyd 集成见 [用户会话与基础服务](LEMONADES-USERMANAGER.md)。
最新数据卷进展：[RAMFS 原子保存及 persona 文件/内核一致性](LEMONADES-RAMFS.md)。
服务端实际响应与日志依赖进展：[muser RPC 与 logd_helper](LEMONADES-MUSER-XPC.md)。
主端点进展：[原厂 NSXPC 权限拒绝与前台会话读取](LEMONADES-NSXPC.md)。
最新基础服务：[会话三方核对及原厂偏好设置读写](LEMONADES-PREFERENCES.md)。
后续：[原厂 FSEvents 回调通过，外部配置刷新差异待修复](LEMONADES-FSEVENTS.md)。
最新对照：[API 跨进程更新及 vnode 通知通过，直接文件更新仍未刷入](LEMONADES-PREFERENCES-REFRESH.md)。
最新身份与应用用户进展：[真实 Mach 发送者身份及 mobile 偏好隔离通过](LEMONADES-AUDIT-MOBILE.md)。
最新监听路径：[定位目录删除回调、纠正 IgnoreSelf 测试条件并验证跨进程事件](LEMONADES-PREFERENCES-LISTENER.md)。
最新桌面服务：[原厂 backboardd 进入初始化、修正日志权限并定位容器服务崩溃](LEMONADES-BACKBOARD.md)。
最新资源修复：[原厂 ICU 数据解除容器日期初始化崩溃；桌面缺事件配置仍失败](LEMONADES-ICU.md)。
最新启动进展：[原厂事件配置接入后 backboardd 完成初始化；20 秒 HID 查询仍为空](LEMONADES-BACKBOARD-CONFIG.md)。
最新输入定位：[HID 服务查找及原厂属性 RPC 可用，设备注册和触控队列接入仍缺失](LEMONADES-HID-CLIENT.md)。
最新触控桥接：[原厂多指编码及合成 HID 传输通过，主屏接入仍受阻](LEMONADES-HID-TOUCH.md)。
最新输入可靠性：[完整触点快照队列、非阻塞与错误恢复、原厂 HID 丢帧恢复链路通过](LEMONADES-INPUT-QUEUE.md)。
本目标保持进行中；完成一个驱动、通过 QEMU 或显示桌面都不构成整体完成。

## 可行性与验收原则

当前基础为 XNU 8796.121.2 / iOS 16.5 研究路线。已有候选 UEFI、最小 XNU、触控组件及离线验证，
尚未在用户的 9R 上启动。没有实机连接时，继续实现源码、系统集成、构建和可复现测试；
无法以模拟器替代硬件身份、时序、外设、电源、温度或流畅度验收。

“全部功能”还包含 Apple 安全硬件、系统服务和服务器依赖。例如 Apple Pay 涉及 Secure Element、
Secure Enclave 和服务端授权，见 [Apple Pay component security](https://support.apple.com/en-ca/guide/security/sec2561eb018/web)。
根据这些依赖，不能承诺软件移植能够实现与 iPhone 等价的全部功能。
此类项目必须记录为未解决的兼容性障碍，不能用接口返回成功、替代服务或关闭检查当作通过。

每项结果至少区分：源码实现、宿主模型、通用 QEMU、9R 实机、日常稳定性。
证据关联源码版本、构建配置、二进制哈希、设备/固件版本及日志。
实机启动后先验证正确性，再测性能；不以削弱内存隔离或系统安全检查换取性能数字。

## 开发顺序与退出条件

| 阶段 | 当前状态 | 阶段验收与下一步 |
| --- | --- | --- |
| 0 构建和恢复基础 | 固件/DTB 提取、候选 UEFI、内核构建和诊断工具已有；实机未验 | 匹配实机版本，建立可恢复的诊断启动和日志；确认 CPU/页大小/EL、内存保留区、GIC/timer |
| 1 9R 最小内核 | 通用 QEMU 到 PID 1；9R handoff 仍关闭 | 完成运行时 ADT/boot_args、内存和单核交接，在实机稳定启动；随后再多核 |
| 2 用户态基础 | 静态进程/VM/管道/COW 与 Mach 消息通过；APFS/dyld/libSystem 和原厂 launchd 启动单个 bootstrap 测试服务在 QEMU 通过 | 账户/persona、正常启动环境、真实服务依赖和完整根镜像逐项接通 |
| 3 可交互桌面 | 有通用显示/HID 基础，S3908 传输和平台接口离线通过 | 9R 显示接管、触屏资源初始化和调度、按键；backboardd/SpringBoard 实机交互 |
| 4 硬件加速与存储 | A650、UFS 尚未实机适配验证 | 固件/电源/时钟/GMU/SMMU/DMA、GPU 提交与同步、合成/应用绘图；UFS 先只读后持久化 |
| 5 通信与多媒体 | 9R 驱动和 iOS 服务接入未完成 | Wi-Fi、蓝牙、GNSS、蜂窝数据/通话/短信、USB、音频、全部相机及视频路径 |
| 6 电源和日常使用 | 未完成 | 电池/充电、热管理、休眠唤醒、传感器、振动、时间、权限、数据持久化、异常恢复 |
| 7 系统/应用服务 | 尚未集成验证 | 应用安装/启动、推送、账户、媒体和安全服务；逐项记录缺失能力与外部阻碍 |
| 8 流畅度和稳定性 | 尚无实机性能数据 | 建立帧时间/输入延迟/温度/功耗测试，与同机型 Android 基线对照，完成长期运行与恢复测试 |

顺序体现依赖，不要求每次只碰一个领域。可以并行研究独立组件，但只能把具备对应证据的项目升级状态。
后续不得为了让某个桌面画面出现而直接套用 redwood/topaz 的 MMIO 地址、分区布局或设备身份。

## 暂定实机质量门槛

以下是工程验收目标，**不是当前测试结果**；设备接入后先测基线再调整场景和阈值。

- 启动与数据：连续 30 次冷启动可达桌面；重启后用户数据一致，无文件系统损坏。
- 基本操作：所有触点、按键、亮度/旋转、锁屏/解锁及常用应用流程有可复现实测。
- 流畅度：先以 1080×2400、60 Hz 的固定桌面/列表/应用场景测试，目标 p95 帧时间 ≤16.7 ms；
  单独记录 p99、长帧、端到端触控延迟和持续负载后的表现，再评估更高刷新率。
- 持续性：30 分钟交互负载和 24 小时混合使用记录 panic、卡死、内存增长、温度与功耗。
- 电源：至少 100 次睡眠/唤醒循环；充电、拔插和过温处理符合实机能力，不能仅验证 UI 数值。
- 功能矩阵：摄像、录音/播放、无线链路、定位、蜂窝、USB 等分别测试正常/失败/恢复路径。
  无法满足的功能保留为未通过，不能从“全部功能正常”口径中悄悄删除。

## 2026-10-26 用户态基础进展

新增 `tools/lemonades/userland/abi_probe.c`，静态 ARM64 Mach-O，不依赖 libc、dyld 或 Apple 系统镜像。
实际在本地新内核的 QEMU 中执行：

1. PID 1 / UID 0 与 Darwin syscall carry/EBADF 返回约定。
2. 64 KiB 匿名映射全部零填充、写入/读取，mprotect 只读/读写调用及解除映射。
3. fork 双返回、子进程 PID/PPID、管道数据/EOF、wait4 退出状态。
4. 子进程修改多个页后，父进程所有原始字节保持不变，验证本场景的 COW 隔离。

测试不证明 mprotect 故障拦截（没有故意访问只读页）、Mach IPC、动态链接、沙箱、launchd 或完整 iOS 安全能力。
测试最后主动 exit(0) 退出 PID 1；只接受阶段标记完整且顺序正确之后出现的预期 initproc panic。
负例包括缺阶段、顺序错乱、ABI FAIL、意外 panic 和错误退出状态；不能仅以出现 COMPLETE 判断成功。
对应 Python 回归总数现为 **70 项**，新 probe 的 14 个 syscall 编号与固定 XNU 源码比对。

使用上一轮已验证内核 `f16e35ce0e0407db`，本轮没有重新构建内核。
两次执行证据保存在 `out/lemonades/userland-verification/f16e35ce0e0407db/`：
`abi/` 为初版 runner 的普通启动，`abi-final/` 为最终 runner 携带旧机型硬件参数的启动。
`verification.json` 记录各产物哈希及最终 runner 对两份日志的重新校验结果。

```sh
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/kernel-smoke.py \
  --program abi \
  --build-manifest out/lemonades/native-deps/build/f16e35ce0e0407db/build.json \
  --output out/lemonades/userland-verification/f16e35ce0e0407db/abi-final \
  --exercise-hardware-guards
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'
```

接续优先事项：Mach 消息/端口与动态用户态依赖审查，同时继续补齐 9R 启动环境证据和触控资源提供者。
