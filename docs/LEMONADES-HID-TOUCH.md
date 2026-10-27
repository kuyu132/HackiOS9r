# 触控事件编码与合成 HID 服务验证

最新身份修复与主屏对照：[设备/事件声明一致性及显式模拟主屏路径](LEMONADES-HID-PROFILE.md)。

日期：2026-10-26。接续 [HID 客户端定位](LEMONADES-HID-CLIENT.md)。
这里只验证触控桥接的离线组成部分，尚未连接 9R 控制器，也未完成系统触控。

## 已实现的事件层

`common/lemonades/hid_touch.c` 将队列 DOWN/MOVE/UP 转换为最多 10 指的 HID 帧。
每次 DOWN 分配新的生命周期标识，拒绝重复 DOWN、无 DOWN 的 MOVE/UP、时间倒退、
坐标越界和标识溢出。输出为待提交状态，发送成功前调用者不覆盖原状态。
释放全部触点可以重试；空状态不制造事件。它不虚构屏幕边缘手势或实测压力数据。

`hid_touch_event.c` 调用原厂 IOKit 生成 hand/finger 事件，分配失败时释放已分配对象。
`hid_touch_probe.c` 使用合成队列记录，由原厂 getter 读回字段；不会发布服务或发送事件。

`backboard-root-v11` 的 QEMU 结果已核验日志：11 条子事件记录覆盖双指 DOWN/MOVE/UP、
槽位复用后更换 identity、全部抬手，以及空释放。坐标与原厂定点转换后的读回值相符，
输出 `HID TOUCH PASS event-encoding`。整体结果仍为 false，后续桌面枚举失败。

## 服务注册与生命周期测试

`hid_service_probe.c` 是单独运行、有父进程超时回收的诊断程序，不是常驻触屏驱动。
设备名称明确包含 SYNTHETIC，Transport=Virtual，Built-In=false。
它准备检查三个独立条件：

1. 服务端确认打开，独立 observer 客户端枚举到相同 registry ID。
2. DOWN/MOVE/UP 经原厂分发接口发送，observer 回调核对 sender、时间、identity、坐标和抬手字段。
3. 移除后原来可见的 ID 消失，属性 RPC 仍可用，期间没有服务器 reset。

仅返回非空对象或 dispatch 接受不构成成功。合成设备在测试结束时移除，不能代替后续
`DESKTOP PASS hid-services`，不能充当实际输入设备。服务器重连会使本次测试失败；
生产桥接仍需实现重连、重新注册及触点恢复。

## 固定版本 ABI 与权限

直接核对 iOS 16.5 / 20F66 arm64 缓存，而不是仅凭第三方原型：

- `IOHIDVirtualServiceClientCreateWithCallbacks`：0x18e563100，要求先调度客户端。
- `_IOHIDServiceClientCreateVirtual`：0x18e55c6c8，version=2 时拷贝 56 字节回调表。
- `IOHIDServiceClientGetRegistryID`：0x18e542b14，返回存于对象 +0x10 的 **CFNumberRef**。
  必须用 CFNumberGetValue 解码，不能将对象指针作为数值 ID；按 ID 查询的接口则接收 uint64_t。
- `IOHIDVirtualServiceClientRemove`：0x18e5889e0，没有可用于判断成功的 Boolean 返回值。
- `_io_hideventsystem_create_virtual_service`：0x18e55aca8。非零类型连接检查 entitlement 位 3；
  缺少权限时可以返回 RPC 成功但输出 service ID=0，高层函数随之返回 NULL。
- 0x18e549358–0x18e549390 将 `com.apple.private.hid.client.event-dispatch` 映射到位 3。
  拒绝日志分支 0x18e5c5bb0 引用同一个名称。位 1 为 event-monitor。

第一次注册运行 `backboard-root-v12`：producer 和 observer 均创建成功，service=NULL，
没有触发事件发送。该版尚未执行到 ID 解码路径；随后已修正该路径的 CFNumber 原型。
拒绝不能归因于触点编码，更不能将空服务算作正常触屏。

后续 `backboard-root-v13` 补充服务端日志，原厂 backboardd 明确记录：PID 23 缺少
`com.apple.private.hid.client.event-dispatch`，注册继续返回 NULL。这与固定二进制检查一致。

显式实验选项 `--hid-service-permissions` 只为自编译的 `hid_service_probe` 声明
`event-dispatch` 和 `event-monitor` 两项，并进行 ad-hoc 签名和内嵌 plist 读回校验。
默认不声明；不会给原厂程序或其他探针增加权限。构建清单记录声明、签名命令、二进制哈希。
`backboard-root-v14` 的构建因本机 codesign 默认以可读文本输出 entitlement 而被校验拒绝，
未生成有效运行镜像；修复为显式 `--xml` 后在新目录重新构建，保留失败目录。

研究内核已有的 miniamfi 会读取程序内嵌 entitlement，但没有验证 Apple 签名信任。
在此环境中声明自编译探针权限，即使能完成实验，也不能证明正式 iOS 安全策略支持该设备。
原厂程序和系统权限检查保持原样。

## 权限对照的实际结果

`backboard-root-v15` / `service-permissions` 在原厂 IOKit 与 backboardd 中依次通过：

- 收到 DeviceOpenedByEventSystem，独立 observer 枚举到相同的数值 registry ID。
- DOWN、MOVE、UP 三次 dispatch 均接受；observer 回调逐次验证 sender、时间戳、
  子事件数量、触点 index/identity/mask、range/touch 和归一化坐标，随后才输出 delivery PASS。
- 移除后同一个 observer 查不到先前的 ID，ClientRecords RPC 仍返回非空数组，未观测 reset。
  backboardd 日志同时记录 digitizer detached 与触点清理。

这证明的是**合成服务的 HID 传输链路**。原厂 BackBoard 将它分类为 externalAccessory、
Transport=Virtual、builtIn=NO、authenticated=NO；三次事件均出现
`ignoring digitizer event for display <main> from unsupported service`。
不能把 observer 收到事件称为 UIKit 或主屏交互成功，也不能直接把这些标志改成 true 当作硬件验收。

测试结束后设备已移除，后续桌面检查仍然输出 `DESKTOP FAIL no HID services`，符合没有常驻
硬件提供者的现状。整个运行 `passed=false`；没有内核 panic 或 backboardd 退出。
其后的 FSEvents/偏好检查没有执行，SpringBoard 未启动。

宿主回归 **119 项通过**，包括触点状态的 10 万条序列与 ASan/UBSan，以及拒绝仅凭注册/发送接受
就将生命周期测试判为成功的检查。四次 QEMU 运行均保留原始失败结果和各阶段标记。

## 待完成

`redwood_input.c` 当前队列溢出静默丢弃最旧记录，多读者争用同一队列，read 忽略 O_NONBLOCK，
也没有完整帧边界或丢失/复位通知。生产桥接必须解决这些问题并在丢失后释放和同步触点。
尚无队列到 HID 的常驻桥接、实际事件到 UI 的验收、完整 GPU/桌面和 9R 实机结果。

编码与注册的原始运行分别保存在 `out/lemonades/hid-touch-verification/`，
`verification.json` 校验各次运行的清单、镜像、内核、日志和源码快照哈希。
ABI 和权限反汇编保存在 `out/lemonades/hid-touch-audit/`。内核仍为 f6d7409e8d4fa72e。

后续：[独立完整快照队列与 HID 丢帧恢复](LEMONADES-INPUT-QUEUE.md) 已补齐新接口的溢出、读者与读取语义；上文 legacy 队列的局限仍适用于旧接口。
