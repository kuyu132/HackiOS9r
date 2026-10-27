# 触控快照队列与 HID 丢帧恢复

后续恢复与效率修复：[HID 服务端重启验证及事件驱动输入等待](LEMONADES-HID-RECOVERY.md)。

最新常驻服务进展：[触控桥接、进程重启恢复与主屏接入条件](LEMONADES-TOUCH-BRIDGE.md)。

日期：2026-10-26。接续 [HID 事件与合成服务](LEMONADES-HID-TOUCH.md)。

## 实现

新增 `/dev/lemonades-touch`，独立于现有 24 字节 `/dev/redwood-touch` 协议。
新节点为 root 只读、0600、独占打开；打开第二个读取描述符返回 EBUSY，写打开返回 EACCES。
同一描述符通过 dup/fork 共享流，应用仍必须指定唯一消费者；并发进行的 read 返回 EBUSY。

每条 120 字节记录包含版本、时间、64 位序号/累计丢失量、原因标志、完整十指状态、
十指坐标和四个按钮的状态。队列容量为 64 条快照。一次 read 返回一条完整快照，
非零短缓冲区返回 EINVAL，空队列的非阻塞读取返回 EWOULDBLOCK，阻塞读取可以被信号中断。
后续内核 035b841ed95f416d 已加入 select 就绪通知，见上方新记录。poll/kqueue 尚未单独验证；
FIOASYNC=0 可用，启用 SIGIO 明确返回 ENOTSUP。

队列满时丢弃积压记录并立即保存当前完整状态，标记 OVERFLOW；重新打开标记 OPEN；
copyout 失败时累计丢失并重新提供 READ_FAULT 快照。序号/丢失计数耗尽后返回 EOVERFLOW，
不允许计数静默回绕。内核复制用户内存时不持有队列锁。
来自用户程序的测试输入设置本次启动内持续的 SYNTHETIC 标记，不能被后续普通输入清除。
物理控制器仍使用原有 redwood_touch_post 发布入口，新快照状态由同一入口维护。

`hid_stream.c` 消费完整快照并调用已有 HID 事件状态层。OPEN、溢出、读取失败、序号缺口
或丢失计数变化都会先释放旧触点，再重建当前触点。这能够区分“手指一直按着”和
“UP、DOWN 都丢失，最终仍按着”，后者必须获得新的 HID 生命周期标识。
正常连续快照只发送状态变化，不重复制造 DOWN。按钮状态目前仅传输，尚不生成键盘事件。

每个事件只在 sink 确认后提交状态。任何发送失败都会将该流标记为 poisoned，禁止继续发送；
因为传输错误可能发生在服务端已接收之后，不能盲目重试。调用者必须移除旧 HID 服务，
为新服务重新初始化状态并读取完整快照。后续常驻守护进程已接入该消费者，见顶部链接。

## 验证设计

宿主直接编译内核使用的队列核心与桥接消费者，使用 ASan/UBSan 验证十指恢复、
丢失 UP/DOWN、100,000 次更新和刻意停止读取、错误记录不修改状态、发送途中失败后停止、
以及序号耗尽。整体宿主回归为 121 项。

`input_queue_probe.c` 在隔离的 QEMU 根盘中操作真正的字符设备，检查独占打开、非阻塞、
零长度/短缓冲区、信号中断、copyout 错误、1000 次写入溢出、重新打开时的活动触点恢复。
测试输入通过 legacy 写入节点注入，明确属于合成数据。

启用 `--check-input-queue` 时，HID 生命周期探针也从新设备读取输入，经过 hid_stream、
原厂 IOKit 及 backboardd 后，由独立 observer 检查 sender、时间、identity、坐标及释放状态。
进一步人为丢失 UP/DOWN，验证释放旧 identity、重建新 identity、最终抬手和服务移除。
成功不等于主屏交互通过：原有 Virtual 外部触控仍会被主屏忽略。

## 首轮发现与修复

首版内核 b0c4c789f9e84af0 / root-v16 已证明新节点的初始快照、短读拒绝、
空队列 EAGAIN 和独占打开等条件；随后在 fcntl(F_SETFL) 返回 ENODEV，测试整体失败。
原因是原有 d_ioctl=eno_ioctl 不支持 FIONBIO。审查固定 XNU 的 kern_descrip.c 还确认
F_SETFL 总会发送 FIOASYNC，因此适配同时接受关闭异步通知，并拒绝未实现的启用请求。
没有删除该测试或把设置失败当作成功。

## 修复后的实测

内核 d1fa2e53c0d21204 / root-v17 在 QEMU 实际通过全部设备节点检查。
1000 次快速写入后，累计丢失计数为 961（1 次 copyout 失败及 960 条溢出丢弃），
读取 40 条剩余快照后得到最新坐标 999；重新打开时仍能恢复这个活动触点，最终 UP 清空状态。
`INPUT QUEUE PASS kernel-contract` 只有全部条件满足才输出。

随后由独立 HID observer 验证 8 次实际发送：普通 DOWN/MOVE/UP、再次 DOWN，
故意丢失 UP/DOWN 后的旧触点释放和新 identity DOWN、最新 MOVE、最终 UP。
`synthetic-queue-recovery`、`synthetic-queue-delivery` 及 `synthetic-removal` 均通过。
这不是在测试中直接调用接收函数：数据来自新内核字符设备，经原厂 HID 服务发送和接收。

完整内核编译及导出检查通过，121 项宿主回归通过。两次运行及源码、输入清单和二进制哈希
核验在 `out/lemonades/input-queue-verification/verification.json`。
整体依旧 `passed=false`：测试服务移除后没有常驻硬件提供者，后续桌面枚举失败。
没有内核 panic 或 backboardd 退出；FSEvents/偏好后续阶段未执行。

所有结果仍区分合成队列/HID 与 9R 实机；
后续已补上常驻虚拟设备提供者；主屏关联、真实控制器时序、休眠唤醒或触屏性能仍未验收。
