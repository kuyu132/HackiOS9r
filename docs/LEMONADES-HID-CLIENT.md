# HID 客户端通信与设备提供者定位

日期：2026-10-26。接续 [BackBoard 配置与初始化](LEMONADES-BACKBOARD-CONFIG.md)。
本轮证明当前 QEMU profile 中原厂 HID 客户端可以查找服务并执行属性 RPC，
但仍无可枚举的 HID 服务。完整桌面检查保持失败，没有触控或实机功能成功结论。

## 固定版本代码依据

直接读取固定 iOS 16.5 / 20F66 arm64 共享缓存，结合导出 trie 与本地符号定位：

- `IOHIDEventSystemClientCreate`，`0x18e54747c`：使用客户端类型 3。
- `IOHIDEventSystemClientCopyServices`，`0x18e55eb1c`：读取客户端内部服务字典，
  CFDictionaryGetCount 为零时直接返回 NULL；这本身不表示服务名查找或 RPC 失败。
- `__IOHIDEventSystemClientRefresh`，`0x18e546004`：调用固定 libxpc 的
  `bootstrap_look_up2`，查找 `com.apple.iohideventsystem`，flags 为 8。
- `IOHIDEventSystemClientCopyProperty`，`0x18e547e48`：序列化键并通过连接端口调用 RPC，
  成功后反序列化响应。不是直接读取与服务端无关的探针本地常量。

CFDictionaryGetCount 和 bootstrap_look_up2 的调用跳板进一步解析到对应模块的精确导出，
避免用最近的本地符号误认函数。属性键从原厂 IOHIDSession 分支引用的 CFString 中解析，
使用所属映射的 slide-info v2 delta_mask/value_add 解码指针，未靠猜测地址或无界字符串扫描。

[Apple 的 bootstrap 私有头文件](https://github.com/apple-oss-distributions/launchd/blob/main/liblaunch/bootstrap_priv.h)
把 bit 3 命名为 BOOTSTRAP_PRIVILEGED_SERVER；实际原型和调用参数仍以本次固定二进制为依据。
[Apple HID 客户端封装](https://github.com/apple-oss-distributions/IOHIDFamily/blob/777ccd9698845aadf711e32d843c8c9b777431d9/HID/HIDEventSystemClient.m)
也通过 CopyServices 和 CopyProperty 获取服务/属性。公开源码用于辅助核对，不能替代固定 iOS 实测。

## 探针与实测

`desktop_probe.c` 增加受限诊断：在第 1 次和第 33 次查询时，分别检查普通与 flags=8 的
bootstrap 查找、客户端对象和描述。所有取得的 Mach send right 均释放。
随后读取原厂 `HIDIdleTimeMicroseconds`、`ServiceRecords`、`ClientRecords`，
只记录返回类型和数值/数量。NULL、类型不符或不可读取的数据不视为成功。
保留最多 20 秒查询、父进程超时回收和非空服务数组要求。
没有给客户端增加 entitlement、修改守护进程身份或更改原厂二进制。

| 运行 | 结果 |
| --- | --- |
| connection / backboard-root-v9 | 两次采样的普通及 flags=8 查找均 kr=0、端口有效，客户端非空；枚举仍 NULL |
| properties / backboard-root-v10 | 查找继续成功，原厂属性 RPC 返回下表结果；65 次枚举仍 NULL，观测 20.044136 秒 |

| 属性 | 首次 | 后次 |
| --- | --- | --- |
| HIDIdleTimeMicroseconds | CFNumber，16013012 | CFNumber，25872600 |
| ServiceRecords | NULL | NULL |
| ClientRecords | CFArray，7 条 | CFArray，7 条 |

这组数据证明该客户端与 HID 服务端的属性通信可用，且没有取得服务记录。
它不能单独区分设备完全未注册、匹配规则或可见性过滤，也不证明事件分发权限。
下一步应检查设备提供者、服务注册与事件传输，不能继续把空枚举等同于 bootstrap 连接失败。
两次整体结果均为 `passed=false`；没有 backboardd 退出或内核 panic。
后续 FSEvents/偏好检查未执行，SpringBoard 未启动。

## 原厂插件与 9R 接入缺口

按固定 rootfs 清单只读提取 `System/Library/HIDPlugins`，记录 26 个 bundle 的 Info.plist，
包括 factory/type 和 Matching 条件。提取后卸载本次磁盘；本轮没有把这些插件批量装进运行镜像。

通用 `ServicePlugins/IOHIDEventServicePlugin.plugin` 的 NSPrincipalClass 为
IOHIDEventServicePlugin，Matching 要求 `HIDServiceSupport: true`。
其余 ServicePlugins 包含特定手柄和 Apple Pencil 等匹配，不能作为 9R 触屏驱动直接套用。
部分 bundle 的可执行内容可能在共享缓存中，磁盘文件缺失不能单独证明 bundle 损坏。

现有 `lemonades_touch.c` 把解析后的触控帧交给 `redwood_input` 队列，
该队列通过 `/dev/redwood-touch` 输出；当前还没有证明它已成为原厂 HID 的可见服务。
后续需要建立有实际输入来源、设备身份明确的桥接或兼容设备接口，并验证事件、释放、
断开及重连。若使用 QEMU 合成输入验证传输，必须与 9R 实际触屏验证分别记录；
不能仅注册一个空服务就声称触控可用。

## 证据与限制

审查代码、反汇编、CFString 解码、公开参考源码、插件目录清单位于
`out/lemonades/hid-client-audit/`。两次实际运行及源码快照位于
`out/lemonades/hid-client-verification/`，`verification.json` 核验输入清单、内核、
镜像、日志和源码哈希，并保留失败结果。
内核仍为 `f6d7409e8d4fa72e`；宿主回归 116 项通过，诊断代码已在 QEMU 实际执行。
原有 AMFI/沙箱和 IOKit 等研究替代实现的限制继续适用。
未改手机分区，未完成实机启动、硬件功能、应用兼容或流畅度验收。

后续：[原厂触控事件编码与合成 HID 服务生命周期验证](LEMONADES-HID-TOUCH.md)。
