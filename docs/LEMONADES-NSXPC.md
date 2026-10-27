# 原厂用户管理 NSXPC 请求与会话读取

日期：2026-10-26。接续 [muser RPC](LEMONADES-MUSER-XPC.md)。
原厂 `com.apple.mobile.usermanagerd.xpc` 已在通用 QEMU 中完成两种实际请求：
无 entitlement 的 persona 查询被拒绝，以及前台会话属性读取成功。
这是最小 XNU 上的用户态集成证据，尚非 9R 实机或完整 iOS 验收。
后续服务导入见 [偏好设置服务](LEMONADES-PREFERENCES.md)。

## 后续：会话数据三方核对

v15 在原有内核上继续通过更严格的检查。新增 `userland/session_state.h`，读取原厂生成的
`/private/var/keybags/usersession.kb`，比较 RPC 回复、保存记录和原厂内核接口
`host_get_multiuser_config_flags` 公布的当前用户 ID：

- 实测 **1 条保存会话、唯一前台会话 UID=501**；RPC 的 **20 个属性全部与保存字典相等**。
- 依照固定 XNU `osfmk/arm/cpu_capabilities.h` 和原厂函数 `0x100066bf4` 使用 `0x3fffffff`
  掩码；不会把 multiuser/secondary-users 标志位当作 UID。
- ID 必须为有效范围内的整数，不能是布尔、浮点或数字字符串；前台标志必须为真正的布尔值。
  拒绝重复 ID、多前台、无前台、缺失记录和任一字段不一致。
- 文件只读打开，拒绝末端符号链接、非常规文件、不安全所有者/权限、空文件及超过 1 MiB 的文件；
  对 plist 容器、嵌套二进制 plist 限制深度、项数与遍历预算。

宿主新增 5 项测试覆盖上述正负场景、损坏数据、缺文件、FIFO、链接、权限和内核查询错误；
先前 NSXPC 回复测试也改用此真实校验函数，输入文件与内核查询均为本地 fixture。
运行证据：`out/lemonades/session-verification/initial/`，v15 的 job exit(0)，观察 10 秒无 panic。
后续 v16 偏好设置集成也保留并通过此检查。该结果证明当前一次性 RAM 启动的一致性，
尚不证明会话切换、持久化重启、受保护密钥或全部用户生命周期。

下文 v13/v14 的非空字典检查与 104 项测试属于前一轮历史结果。

## 端点与 error 37

检查原厂 iOS 16.5 usermanagerd 的 Objective-C 元数据及 ARM64 指令，发现：

- main 的 `0x10004752c` 调用 `0x10005bac8`，创建 UMSyncXPCListener；
  `0x100047530` 再调用 `0x100066264`，创建 RXSyncXPCListener。
- 两处 NSXPCListener 初始化均使用 `com.apple.mobile.usermanagerd.xpc`。
  UMSync 的 delegate 在 `0x10004ed7c` 导出 UMSyncXPCProtocol / UMSyncService。
- `fetchPersonaListforPid:withCompletionHandler:` 的 UMSync 实现在 `0x100058ca4`。
  缺少 `com.apple.usermanagerd.persona.fetch` 时，`0x100058f00..0x100058f3c`
  构造 `NSPOSIXErrorDomain / EPERM`，回复 `(nil, error)`。
- `foregroundUserSessionAttributesWithReply:` 在 `0x100054198` 进入工作队列；
  `0x1000151a8` 从已加载的 session 数组查找前台项，未找到时返回错误。

重复注册是 error 37 的候选原因。测试中该 warning 仍出现，但紧接着原厂服务能够响应请求，
因此不能再将它单独视作整个用户管理端点不可用的证据。尚未跟踪每次注册的运行时调用栈，
不宣称 warning 根因已经完全确认或消除，也未验证 RXSync/RDServer 的全部行为。

## 已实现与实际结果

新增 `tools/lemonades/userland/nsxpc_probe.m`，由镜像构建器交叉编译、链接原厂 Foundation，
由 bootstrap 测试 job 启动为独立进程。公共 iOS SDK 将 Mach-service initializer 标为 unavailable；
诊断程序使用局部协议声明调用已在原厂二进制确认的 selector，没有修改 SDK 或原厂服务。

两个请求顺序执行，每个最多等待 10 秒，父进程最多约 25 秒后杀死并回收超时子进程：

1. 查询测试进程自己的 persona 列表。测试程序不带 persona-fetch entitlement，
   只接受 nil 数据和精确的 POSIX EPERM。实际原厂日志显示
   `In UMSyncServer: fetchPersonaListforPid entitlement failure:14`，客户端收到 code=1。
2. 读取前台会话属性。只接受无错误、非空 NSDictionary；实际收到 **20 个属性**，
   原厂日志同时记录 `Finding ForeGround session` / `FOUND ForeGround session`。
   本轮验证了返回类型和非空数据，尚未逐字段核对会话属性与内核或持久化状态的一致性。

最终 v14 根镜像测试通过，bootstrap job exit(0)，之后观察 10 秒无 panic。
此前的 RAMFS rename、persona 文件/内核 ID 一致性、凭证、notifyd 和 muser RPC 检查继续通过。
原厂 daemon SHA-256 保持为：
`ca0cba10ad90ca78f739b6c3e3f2ebf48ace5af0b70b8bc19fe0fa0383543568`。

日志检查器新增直接识别 `NSXPC FAIL`，即使同时存在成功标记也判失败。
宿主回归 **104 项通过**；新增测试用进程内 FixtureConnection 驱动真实 probe 代码，
13 个回复场景覆盖错误域/错误码、错误类型、nil/空数据、传输错误及数据伴随错误。
测试不连接宿主用户管理服务，不能代替上述原厂 QEMU RPC 测试。

## 证据与复现

- `out/lemonades/nsxpc-audit/`：原厂哈希、方法和注册路径指令片段、范围及待办。
- `out/lemonades/nsxpc-verification/initial/`：v13，只验证 persona 权限拒绝，通过。
- `out/lemonades/nsxpc-verification/foreground/`：v14，增加前台会话读取，通过。
- `out/lemonades/nsxpc-verification/verification.json`：各次结果、源码与产物哈希复核。
- `usermanager-root-v12` 是遇到 SDK availability 编译错误的中间目录，没有成功构建清单。

沿用已完成内核构建 `f6d7409e8d4fa72e`，本轮没有重建或修改内核。

```sh
python3 tools/lemonades/build_dynamic_root.py --mode usermanager \
  --rootfs out/lemonades/ios165-source/rootfs-launchd-users \
  --core-services out/lemonades/ios165-source/core-service-provider \
  --log-helper out/lemonades/ios165-source/logd-helper-provider \
  --output out/lemonades/nsxpc-root-new
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/dynamic-smoke.py \
  --root-manifest out/lemonades/nsxpc-root-new/build.json \
  --build-manifest out/lemonades/native-deps/build/f6d7409e8d4fa72e/build.json \
  --output out/lemonades/nsxpc-verification/new --timeout 90
```

输出使用全新目录。没有接入或刷写手机，没有更改权限、boot mode、commpage 或硬件身份来获得成功回复。
RAMFS 易失性、AMFI stand-in、完整日志/用户会话生命周期、其他系统服务及硬件驱动限制继续适用。
下一步可核对会话字段、查明正常启动环境及更多原厂依赖；两项 RPC 成功不意味着完整会话管理已完成。
