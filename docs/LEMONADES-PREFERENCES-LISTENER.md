# 偏好服务的目录监听路径

日期：2026-10-26。接续 [消息身份与 mobile 偏好隔离](LEMONADES-AUDIT-MOBILE.md)。
本轮只读分析固定 iOS 16.5 / 20F66 的原厂 CoreFoundation，并扩展文件事件集成检查。
没有修改原厂服务、内核通知或缓存策略。

## 静态证据改变了排查方向

原厂 arm64 `cfprefsd` 的入口 `0x100003f68` 直接跳转至
CoreFoundation 的 `__CFXPreferencesDaemon_main`。对共享缓存进行虚拟地址映射，并读取
配套 `.symbols` 文件，取得该库 10,467 个本地符号。缓存布局依据
[Apple dyld 格式定义](https://raw.githubusercontent.com/apple-oss-distributions/dyld/main/include/mach-o/dyld_cache_format.h)，
实际分析输入与参考头文件均记录哈希。脚本是本次固定输入的只读分析工具，不能当作通用可执行文件提取器。

| 固定缓存中的地址 | 观察 |
| --- | --- |
| `0x186f63738` | initializeFSEvents block 从 MobileCoreServices 动态查询 FSEventStream 系列函数 |
| `0x186ed6f18` | 重建流：回调为 `0x186e673d4`，create flags 为 `0x19`（CFTypes / IgnoreSelf / FileEvents） |
| `0x186e673d4` | `_deletionStreamCallback` 对 flags 使用 `0x20200` 掩码；两位必须同时出现才处理对应路径 |
| `0x186e67458`–`0x186e67470` | ItemRemoved / ItemIsDir 条件分支；普通 plist 文件替换不满足这条分支 |
| `0x186f659c4` | handleFlushSourceForDomainMessage 的 block 调用 respondToFileWrittenToBehindOurBack |
| `0x186edb888` | handleFlushManagedMessage 的 block 也调用该响应方法 |

因此，“服务使用 FSEvents”不等于“所有文件替换都会触发其缓存刷新”。此前普通文件创建、
vnode 通知和 API 更新的结果，与这条仅处理目录删除的回调没有矛盾。
直接分支检索不能枚举所有 Objective-C 间接调用，也没有证明原厂 iOS 永远不支持外部文件刷新。
现阶段仍不足以把外部替换超时定性为 RAMFS 或 FSEvents 的确定缺陷。

## 实现与验证范围

`fsevents_probe.c` 保留原有文件创建检查，新增目录删除场景：先在独立临时目录中注册原厂流，
由独立 exec 子进程创建子目录，收到创建回调后再由另一子进程删除。使用 CFTypes / IgnoreSelf / FileEvents，收到 CFArray 路径后逐项检查
字符串类型、目标路径、ItemRemoved / ItemIsDir、有效事件 ID 及无丢失标志。
流停止并失效后清空回调队列，再释放上下文，避免异步使用已退出的栈数据。

本场景验证“被监听父目录中的子目录删除”。没有删除 cfprefsd 的真实 Preferences 目录，
也不等同于原厂目录缓存失效逻辑已经执行；监听根目录本身被删除是另一个尚未验证的场景。

bootstrap 将独立 FSEvents 检查放到偏好设置检查之前，使后者失败不会遮住文件事件结果。
所有旧的偏好检查仍保留，任何失败仍导致整个集成失败。
宿主 callback fixture 增加 CFArray 正例、文件类型冒充目录、非字符串、数组长度不足及丢失事件负例；
总计 18 个 callback 子场景，不向宿主文件事件服务注册流。

运行使用已有内核 `f6d7409e8d4fa72e`，根镜像与结果分开记录：

- v25 / initial：文件创建通过；目录删除超时。测试错误地让监听进程自行删除，而 0x19 含 IgnoreSelf。保留失败结果。
- v26：只完成构建；该版本增加创建回调等待，但仍由监听进程操作。核对 SDK 发现 IgnoreSelf 后未运行此版本。
- v27：修正为独立生产者，保留 0x19，与目录创建回调同步后再删除。运行结果另见下文。

早期注释把 0x08 解释为 WatchRoot，已按本机 Apple SDK 的 FSEvents.h 更正：WatchRoot=0x04，IgnoreSelf=0x08。
这次错误属于测试设计，不能归为内核目录删除缺陷。
详细证据位于 `out/lemonades/preferences-listener-audit/`；运行产物位于
`out/lemonades/preferences-listener-verification/initial/`。

v27 / `cross-process` 已收到实际目录创建回调，然后收到同一路径的删除回调，
flags=`0x20300`、event ID=`2284`，包含 ItemRemoved / ItemIsDir；
创建/删除生产者分别为 PID 19 / 20。事件还包含 ItemCreated，测试按所需标志判断，不要求没有其他合法标志。
串口出现 `FSEVENTS PASS file-create`、`FSEVENTS PASS directory-delete`；
之后 mobile 隔离、API 更新、vnode 通知检查也通过。
宿主 114 项回归通过，`git diff --check` 通过。宿主 fixture 不替代以上真实服务调用证据。

v27 整体仍失败于 `preferences external cache refresh timeout`：40 秒窗口结束后，
文件保持外部新值，原客户端与 fresh reader 仍读旧值。无内核 panic。
`verification.json` 核对两次运行的构建、输入清单、镜像、源码快照和日志，保留真实失败状态；
不将 v25 测试设计问题与 v27 原有缓存刷新差异混为一项缺陷。

下一步依据：目录删除事件的跨进程传递已取得证据，尚无依据修改 RAMFS 通知。
继续跟踪原厂 flush-source 消息的发起条件，并推进完整用户会话和桌面服务依赖；
原厂系统对直接 plist 替换的对照仍缺失，不能据当前单一实验下普遍结论。

这项排查没有证明完整 iOS 用户态或实机硬件兼容。继续区分正常 API 用法、原厂实现条件及
真正缺失的内核能力；没有证据时不通过禁用缓存或伪造事件改变服务行为。
