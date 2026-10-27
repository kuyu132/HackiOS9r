# HID 服务端恢复与输入就绪通知

最新身份修复与主屏对照：[设备/事件声明一致性及显式模拟主屏路径](LEMONADES-HID-PROFILE.md)。

2026-10-26，接续 [常驻触控桥接](LEMONADES-TOUCH-BRIDGE.md)。本轮解决常驻桥接的空队列轮询问题，并补齐原版 HID 服务端异常退出后的恢复验证。仍未在 OnePlus 9R 上运行，不构成完整 iOS、主屏交互或功耗性能验收。

## 服务端故障恢复

构建选项 `--check-hid-server-restart` 必须同时启用 `--check-touch-bridge`；只用于独立的研究根镜像。探针通过 `proc_listallpids` 找到唯一的 `/usr/libexec/backboardd`，没有唯一匹配就拒绝注入故障。它在触点仍按下时结束该进程，并记录服务端 PID、桥接 PID 和发起探针 PID。

验证要求：

1. 原有观察客户端确实收到 reset 回调。
2. 旧桥接以 `status=75 reset=1` 退出，launchd 启动不同 PID 的桥接和 BackBoard。
3. 保留订阅的独立观察客户端收到新桥接恢复的按下事件，随后收到新的移动事件。
4. 正常停止新桥接时收到抬手，服务消失；默认配置仍拒绝合成输入。

日志检查关联 fault 记录、对应 probe 发起的 SIGKILL、两个服务的启动记录与恢复事件。只有全部匹配，才把这一条预期 BackBoard 退出从意外退出列表中排除；错误发起 PID、缺少恢复或任何额外 BackBoard 退出仍导致失败。该测试没有放宽桌面、偏好或完整启动的检查。

首轮 root-v20 / 内核 `d1fa2e53c0d21204` 已通过上述恢复路径，证明原有 reset 处理能在这次服务端故障下工作。后续等待机制修改仍重跑相同故障路径。

## 消除 10ms 空队列轮询

`redwood_input.c` 为新快照节点实现 `d_select`。数据可读、序号耗尽或节点关闭时返回读就绪；空队列使用 `selrecord` 登记等待。登记、队列状态判断与唤醒都由同一 `touch_lock` 保护，避免检查完空队列到登记之间丢失通知。

发布输入和 copyout 失败后的新快照会 `selwakeup`；最后关闭节点时 `selthreadclear` 清理等待关系。legacy 节点保持原有无 select 合约行为。实现依据固定 XNU 8796.121.2 的 `sys/select.h`、`sys_generic.c` 和 `waitq.c`；未修改这些基础设施。

桥接收到 EAGAIN 后使用无超时 `select` 同时等待输入节点与非阻塞通知管道。SIGTERM/SIGINT、HID reset 和 opened 属性回调向管道写入通知，从而避免“刚检查状态尚未等待时收到退出请求”的丢失唤醒。管道两端一直保留到进程退出，异步回调不会写入已被回收利用的描述符。启动等待和同步 RPC 超时仍独立保留。

这消除了源码中的周期性空闲读取；尚未做实机功耗、延迟、满负荷或长时间稳定性测量。没有宣称 poll/kqueue 的独立兼容性测试已完成。

## 实际验证

新内核 `035b841ed95f416d` 完整编译、导出与未定义符号检查通过。123 项主机测试通过，包含新增故障退出匹配检查，以及既有队列/触点 ASan/UBSan 检查。

| 运行目录（均在 `out/lemonades/hid-restart-verification/`） | 根镜像 / 内核 | 阶段结果 |
| --- | --- | --- |
| `baseline` | v20 / d1fa2e53c0d21204 | 服务端死亡、桥接重建、按下恢复及后续移动/抬手通过 |
| `readiness` | v21 / 035b841ed95f416d | 真实字符设备的 select 合约及原队列测试通过 |
| `event-driven` | v22 / 035b841ed95f416d | 新等待机制下，发送、自身重启、服务端重启、正常停止和默认合成输入拒绝通过 |

就绪通知测试覆盖：打开后的立即就绪、空队列超时、延迟子进程写入唤醒、信号中断、copyout 恢复通知、1000 次写入溢出、读空、带等待登记关闭及重新打开。仍得到累计丢弃 961 条、读取 40 条溢出后快照、最新坐标 999 的既有结果。

事件驱动运行中，reset 前的桥接记录 `waits=2 input_wakes=0 control_wakes=2`；重建后的桥接记录 `waits=3 input_wakes=1 control_wakes=1`，发送 API 接受 3 帧（恢复按下、移动、停止抬手），这些事件均由独立观察客户端核对。这些计数描述本次短运行，不是性能指标。

三轮完整系统结果仍为 `passed=false`：测试结束移除虚拟设备后，DESKTOP 检查报告无 HID 服务；后续 FSEvents/偏好阶段未执行。两个故障测试各主动结束一次 BackBoard；除此之外没有额外 BackBoard 退出，没有内核 panic。主屏仍拒绝没有内建设备身份和显示归属的虚拟触控。

可复核证据汇总在 `out/lemonades/hid-restart-verification/verification.json`，保留各次运行独立的结果、日志、源码快照与镜像/内核哈希。

## 尚未解决

真实 S3908/GENI 控制器采样、屏幕归属、输入与显示坐标标定、休眠与唤醒仍需接入和实机验证。BackBoard 高频反复崩溃、负载下的多指恢复和长期运行仍未验收。图形加速、SpringBoard、持久存储和其他手机外设的缺口没有因本轮输入服务通过而消失。
