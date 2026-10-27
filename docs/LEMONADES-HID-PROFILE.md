# HID 设备/事件身份一致性与模拟主屏路径

2026-10-26，接续 [服务端恢复及事件等待](LEMONADES-HID-RECOVERY.md)。本轮修复设备声明和事件字段不一致的问题，并在明确标注的测试镜像中观察原版 BackBoard 主屏触点处理。**仍没有实机触控、应用事件交付或完整 iOS 成功结论。**

## 实际修复

此前 `hid_device.c` 注册 `Built-In=false`，而 `hid_touch_event.c` 无条件设置父事件的 `IsBuiltIn=1`，子触点也没有显式匹配该声明。这会使服务身份与事件身份不一致。

现在编码函数显式接收 `built_in`（仅允许 0/1），同时设置父事件和每个子触点。常驻桥接的服务属性与事件编码使用同一状态；默认值为 0。旧的短期虚拟服务探针也显式传入 0，已重新编译检查。

原版 IOKit 编码测试分别核对 0 和 1 两种配置的父/子字段，保留已有触点与坐标检查，并在有效帧上验证非法配置拒绝。独立观察客户端检查实际接收事件的父/子字段，再通过独立服务对象读取 `Built-In` 和 `Transport` 核对设备声明。桥接自身重启、HID 服务端重启后重复核对服务属性。

## 隔离模拟模式

`build_dynamic_root.py --test-integrated-touch` 必须配合 `--check-touch-bridge`。只有这个显式测试构建才编入 `TEST_INTEGRATED_TOUCH`，并在 launchd 参数中添加 `--allow-synthetic --test-integrated`。普通构建不接受额外的模拟参数。模拟服务产品名明确包含 `TEST simulated integrated touch`，Transport 仍为 Virtual，不宣称物理来源。

测试模式将服务和事件的内建标志共同设为 1，目的只是观察前次定位的原版主屏分类路径。默认无参数桥接仍声明外部设备、拒绝 SYNTHETIC 输入。本轮没有接入真实资源所有者，也没有把“没有合成标记”等同于物理硬件准备完成。

## 对照运行结果

全部运行使用既有内核 `035b841ed95f416d`，本轮没有内核修改。

| 目录（`out/lemonades/hid-profile-verification/`） | 根镜像 | 观察 |
| --- | --- | --- |
| `external` | v23 | 服务/父事件/子事件的内建标志均为 0；发送、自身重启、停止及默认输入策略通过；原版主屏仍拒绝该外部设备 |
| `simulated-integrated` | v24 | 显式模拟内建触屏；原版 BackBoard 获得主屏 digitizer、记录 contact 1 touching/none，异常移除时取消仍按下的触点 |
| `external-recovery` | v25 | 修正后的默认外部模式在 HID 服务端死亡后仍恢复，后续移动、抬手及设备属性核对通过 |

模拟运行的关键原版日志为 `acquired main display digitizer`、`contact 1 presence: touching`、`contact 1 presence: none`，以及带对应 senderID 的取消记录。首个桥接被强制结束时，原版触点状态包含仍按下的 contact 和 hitTest destination，随后进入取消路径；重启后的桥接正常退出前处理抬手。

这比仅确认虚拟设备注册或独立 HID monitor 收到事件更进一步，但不是应用收到事件的证明。日志中的 hitTest context/clientPort 尚未对应到实际应用；SpringBoard 和交互画面也未验证。此 QEMU 根环境报告的主屏尺寸是 1125×2436，不能作为 OnePlus 9R 屏幕初始化或标定结果。

该显式模拟模式中原版日志出现 `authenticated: YES`。本实验没有执行或验证 Apple 硬件认证、Secure Enclave、真实安全启动或 Apple 服务端授权；不能把这个软件分类字段解释为那些功能已经实现。原厂二进制未修改。

## 可复核判定

`tools/lemonades/analyze_touch_routing.py` 从桥接日志取得 initial/restarted 两个 PID 与 registry ID，逐个关联原版 BackBoard 的附加、主屏分类、触点处理、取消及移除记录。

由于 contact 日志本身不带 sender，分析器只接受没有重叠设备的生命周期区间；缺失日志、重复 ID、其他设备混入、错误取消 sender、缺少抬手或日志截断均不能通过。输出的 `routing_observed` 只表示对应模式的路由行为已观察到：外部模式的预期行为就是被拒绝，不能把其 true 当作主屏成功。输出始终保留 `app_delivery_verified=false` 和 `physical_input_verified=false`。

125 项主机测试通过，包括新分析器对缺失、串错设备和重叠日志的拒绝测试。三轮完整系统结果仍为 false：移除测试设备后，DESKTOP 检查仍报无 HID 服务，后续 FSEvents/偏好阶段未执行。默认恢复测试主动结束一次 BackBoard；其余无意外 BackBoard 退出，无内核 panic。

汇总及哈希索引：`out/lemonades/hid-profile-verification/verification.json`。

## 后续缺口

真实 S3908/GENI 平台资源所有者、控制器自动启动和屏幕归属尚未连接到 HID 设备身份。UISensor 请求的触控检测/电源模式也尚未映射到硬件；目前模拟输入能进入触点状态机，不代表休眠、电源或锁屏策略已经适配。下一阶段仍需实际应用接收与显示链路，以及实机控制器/屏幕证据。
