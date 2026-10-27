# 常驻触控桥接与主屏接入限制

最新身份修复与主屏对照：[设备/事件声明一致性及显式模拟主屏路径](LEMONADES-HID-PROFILE.md)。

后续恢复与效率修复：[HID 服务端重启验证及事件驱动输入等待](LEMONADES-HID-RECOVERY.md)。

2026-10-26。目标仍是在 OnePlus 9R 实机运行完整 iOS；本轮交付为最小 XNU/iOS 16.5 研究环境中的常驻输入服务。没有连接手机，没有刷机，也没有得到真实触控或主屏交互通过结论。

## 实现

`tools/lemonades/userland/touch_bridge.c` 独占 `/dev/lemonades-touch`，把完整触点快照交给已有 `hid_stream` 状态机，再通过原版 IOKit 虚拟服务发送多指事件。每个进程只建立一组输入与 HID 会话；不复用断线后的异步回调上下文。读取异常、格式错误、发送结果不确定、服务 reset/关闭都退出失败，由 launchd 重建进程；新进程从 OPEN 完整快照恢复当前触点。

正常 SIGTERM/SIGINT 会尝试发送全部抬手，再移除服务、关闭输入节点和删除就绪状态文件。启动和同步 RPC 有超时保护。SIGKILL 或看门狗强制退出不能承诺补发抬手；恢复依赖旧服务退场和新服务完整快照重建。单进程 `frames` 是发送 API 接受数，不能单独证明事件送达。

构建参数 `--touch-bridge` 安装 `/usr/libexec/lemonades-touch-bridge` 和 `net.hackios9r.touch-bridge` job。失败退出触发重启，节流间隔 3 秒；成功退出不重启。当前根文件系统的原厂 launchd 将这些 job 装载到 user/501 域，桥接通过 `UserName=root` 运行。这不是已经验证的实机系统域部署。

默认拒绝内核标记为 SYNTHETIC 的输入并成功退出，避免无意义的重启循环。该标记在本次内核启动期间保持；恢复非测试输入需要重新启动干净环境。只有 `--check-touch-bridge` 测试镜像把 `--allow-synthetic` 加到桥接参数。该测试选项要求 `--touch-bridge`，不能与独占队列或短生命周期 HID 探针共用镜像。

桥接自编译二进制仅声明 event-dispatch entitlement；独立探针仅声明 event-monitor。构建读取回嵌入的 XML entitlement 并核对、保留哈希。研究内核接受自签名声明，不代表已通过 Apple 信任链；原厂二进制未修改。

## 验证方法与证据

固定使用已验证内核 `d1fa2e53c0d21204`，本轮无需内核修改。第一轮根镜像 v18，第二轮 v19 增加默认策略测试和更严格的日志检查。

探针通过独立 IOKit 观察客户端核对 sender、触点编号、identity、时间、范围、按压状态和坐标，然后：

1. 注入按下，要求常驻桥接实际送达。
2. 核对 root 所有的状态文件、进程可执行路径和可见设备 ID 后，SIGKILL 指定桥接进程。
3. 要求 launchd 创建不同 PID、不同设备 ID，旧服务消失，新服务送达仍按下的触点。
4. SIGTERM 新进程，要求收到抬手、设备移除，并观察 5 秒无就绪进程重启。
5. 在同一带有 SYNTHETIC 标记的内核状态中，另行启动无测试参数的桥接，要求成功退出、没有发送事件、没有发布就绪状态、输入独占节点已释放。

日志检查还关联对应 PID 的 launchd spawn、SIGKILL 与 exit(0) 记录。探针由 bootstrap 父进程限时 90 秒；独立观察客户端 reset、事件错误或生命周期缺项都会失败。

运行目录：

- `out/lemonades/touch-bridge-verification/supervision/`：v18 首次常驻发送、异常重启恢复、正常停止通过。
- `out/lemonades/touch-bridge-verification/policy/`：v19 四项阶段检查均通过，`bridge_lifecycle_verified=true`；默认桥接退出码 0、发送帧数 0。整体结果仍为 false。
- `out/lemonades/touch-bridge-verification/verification.json`：实际运行、源码快照、镜像、内核、签名二进制、输入提取记录和审计文件的哈希索引。

主机侧 122 项测试通过，包括队列/状态机的 ASan/UBSan 测试及新增日志判定回归。桥接结束后设备已移除，后续 DESKTOP 检查仍按原要求失败，不能把本轮阶段通过当作整个系统通过。后续偏好/FSEvents 检查未执行。

## 原版 BackBoard 拒绝主屏触控的条件

审计固定原版 `backboardd`（iOS 16.5 / 20F66），输入哈希与固件提取记录核对一致。类为 `BKHIDDirectTouchEventProcessor`，方法 `processEvent:sender:dispatcher:`，入口 `0x10003aea0`；拒绝日志引用位于 `0x10003b098`。

在非触控板分支，`0x10003afd8` 起读取 `isBuiltIn`，与 `bool(displayUUID)` 比较；二者相等会转入 unsupported-service 拒绝分支。不同才继续检查 usage：page 13，usage 1/4/32。对应 selector stub：`displayUUID=0x100097b40`、`isBuiltIn=0x1000997e0`、`primaryUsagePage=0x10009b360`、`primaryUsage=0x10009b340`。

本轮虚拟服务为 `Built-In=false`、没有 `displayUUID`、page 13/usage 4，因此落入拒绝分支。运行日志与该静态路径吻合。这里定位到的是显示归属与内建设备条件；不能仅凭日志中的 `authenticated:NO` 断言是认证检查导致此次拒绝。也不能据此断言改一个属性就能完成触控或桌面适配。

详细反汇编和可复算脚本保留在 `out/lemonades/touch-bridge-audit/`，主要结论见 `main-display-gate.json`。没有修改原厂判断、伪造内建设备身份或宣称通过主屏验收。

## 剩余工作

- 后续已改为 select 与通知管道等待，见上方新记录；实机功耗和延迟尚未测量。
- 本文首轮仅验证桥接自身重启；后续已补测一次 HID 服务端死亡后的恢复，尚未覆盖高频故障和长时间负载。
- 需把已识别的真实触控控制器、屏幕归属与内建设备属性连接起来，再验证主屏事件处理和应用交互。真实 S3908/GENI 中断、时序与显示标定需要实机证据。
- 图形加速、SpringBoard、持久存储、音频、相机、无线、电源管理和 Apple 安全硬件/服务依赖仍未完成，整体流畅度与全部功能目标远未验收。
