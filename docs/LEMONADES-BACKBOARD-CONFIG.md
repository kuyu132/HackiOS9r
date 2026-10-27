# BackBoard 原厂事件配置与启动观测

日期：2026-10-26。接续 [ICU 与容器初始化修复](LEMONADES-ICU.md)。
原厂 backboardd 在通用 QEMU 中越过缺事件配置的异常点并记录 startup complete，
但 HID 服务枚举仍失败，完整桌面与 9R 实机功能均未完成。

## 原厂配置接入

从固定 iOS 16.5 / 20F66 rootfs 只读提取 `System/Library/BackBoard`。
目录实际只有 `EventProcessorConfiguration.plist`；平台覆盖文件在该目录中不存在，
不能因为访问覆盖文件返回 ENOENT 就推断必须创建一个。

配置为 1313 字节、UID/GID 0、0644，SHA-256：
`1360a59a33789cebea9db2f652ddaf42c6978158a98c2fce72cb43810ea9ed01`。
它定义 19 个处理器的创建顺序，以及键盘、指针、触屏、接近、加速度等事件处理链。
所有引用均在创建顺序中。仅在 backboardd 文件搜索类名字符串不能判断运行时类是否存在，
共享缓存和 Objective-C 元数据也可能提供它们；没有据此删除或替换处理器。

`build_dynamic_root.py --backboard-config <backboard-config-provider>` 要求已启用 backboard，
校验提取清单的固定来源、文件 SHA-256 和所有者元数据，导入配置原始字节。
提取目录与 v7/v8 镜像中的配置哈希一致，Apple 二进制未改。
此选项为显式导入，历史 profile 的输入和结果保持不变。

## 启动等待与运行结果

首版新镜像 v7 的 HID 查询发生在 backboardd 仍初始化亮度系统时，
一次空查询就结束了运行，尚未观测到读取事件配置后的路径。
这一结果不能证明修复有效或无效。

`desktop_probe.c` 现使用单调时钟，在最多 20 秒内重建客户端并重新查询服务，
请求间隔 250 ms；父进程仍有 30 秒等待和强制回收，以约束阻塞的 API。
只接受原厂 API 实际返回的非空服务数组，空结果继续失败。
检查器仍拒绝 backboardd 退出记录；没有注入设备、事件或伪造服务数组。

| 运行 | 观测与结果 |
| --- | --- |
| 先前 with-icu / v6 | 缺原厂事件配置，backboardd 抛异常并 SIGABRT；整体失败 |
| config / v7 | 配置已导入，但单次查询过早终止，初始化效果未验；整体失败 |
| config-observed / v8 | 64 次查询，实际观测 20.157232 秒，结果始终为 NULL；整体失败 |

v8 原厂日志显示 HID event processing、HID server、system shell servers 等初始化走完，
随后记录 `startup complete. 7.353s elapsed`。观测期间没有此前的缺配置异常、
backboardd 退出记录或内核 panic。该数值是这次 QEMU 日志，不是 9R 启动性能。
可以据此确认本次配置缺失阻碍解除，不能据此宣称 HID 事件传递、显示输出或完整桌面已可用。

## 剩余问题

- HID 查询仍为空，需要进一步区分客户端连接/权限、服务注册及输入设备提供者。
  当前最小内核并未证明有完整 HID 设备接入；不能通过添加空设备来升级整体通过状态。
  后续 [客户端审查与属性 RPC 测试](LEMONADES-HID-CLIENT.md) 已确认服务查找和属性通信可用，
  设备注册、匹配可见性及触控队列接入仍需完成。
- 显示 2/3/4 的 swap_end 返回 `e00002d7`，固定 SDK 的 IOReturn.h 对应
  `kIOReturnOffline`。日志另见 wireless0/1/2 无可用模式；尚未证明这些错误与主显示的关系。
- 原厂 Data Migration 客户端报告 XPC 连接无效和 success NO；随后打印的
  “Migration complete (if performed)” 不能视为迁移成功。
- Boot UI 没有找到 apple-logo，反复访问缺失的 OpenGLES framework 资源目录，
  还有 RunningBoard、附件、传感器等依赖缺失。尚无实际像素输出验证。
- SpringBoard 尚未启动；FSEvents/偏好等后续检查因本 profile 的 HID 失败而未执行。

原有最小 XNU 的 AMFI/沙箱、IOKit/显示等研究替代实现限制继续适用。
手机未连接，未执行刷写或实机测试，完整功能与流畅度目标保持未完成。

## 证据

`out/lemonades/backboard-config-audit/` 保存配置结构、类名搜索范围、staged 文件哈希及审查记录。
`out/lemonades/backboard-config-verification/` 保存两次新运行；
其中 `verification.json` 同时关联前一轮 v6 对照，核验实际运行结果、
内核与镜像、输入提取清单及源码快照，三次均保留 `passed=false`。
内核仍为 `f6d7409e8d4fa72e`，没有重编译或修改内核。
宿主回归 116 项通过，新增探针代码已交叉编译并在上述 v8 中执行。
