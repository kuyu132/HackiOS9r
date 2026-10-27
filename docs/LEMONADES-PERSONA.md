# Persona 初始化与进程身份

日期：2026-10-26。接续 [launchd/bootstrap](LEMONADES-LAUNCHD-BOOTSTRAP.md)。
本轮修复继承补丁中掩盖 persona 缺失的行为，验证服务凭证并定位原厂提供者。
完整 iOS、正常启动环境、persona 初始化及 9R 实机功能仍未完成。
后续原厂提供者的运行和初始化修复见 [用户会话与基础服务](LEMONADES-USERMANAGER.md)；
本文“尚未启动 daemon”和 99 项测试为本阶段的历史状态。

## 内核修复与实际验证

原 `redwood.patch` 修改了 `spawn_validate_persona` 和 `spawn_persona_adopt`：跳过管理权限检查、
允许找不到 persona 的请求，并将请求的 UID/GID 直接赋给新进程。删除这四个补丁 hunk，
恢复固定 Apple XNU `c54f35ca767986246321eb901baf8f5ff7923f6a` 的两段函数。
测试将当前 canonical patch 实际应用到原始 kern_exec.c，再逐字比对函数，避免只检查旧 checkout。

新 native minimal 内核完整编译及导出检查通过，构建键 `a336b7dfe69cbf78`，SHA-256：
`621683320bdb141e800cdfbc8fd3d4591e10bdb39664727976b65ea713bf44a9`。

在新内核和独立根镜像下实际通过：

1. 原厂 launchd/xpcproxy 启动的服务位于 `user/501` 域，但实际 UID/EUID/GID/EGID 均为 0，
   与测试 plist 的 `UserName=root` 相符。域名不能代替进程凭证测量。
2. bootstrap check-in/lookup 与未知服务错误路径继续通过。
3. 服务 fork 子进程，设置补充组/GID/UID 为 501，再通过原厂 libSystem 请求 persona
   `0x7ffffffe`、OVERRIDE、目标 UID 0。无管理 entitlement 的请求返回 EPERM，子进程仍为 UID 501。
4. 父服务确认子进程正常退出；launchd 确认服务 exit(0)，随后 10 秒观察无 panic。
5. 同一新内核上的静态 Mach+BSD 回归及旧机型硬件参数隔离测试通过。

此结果仅证明所测拒绝路径和凭证保持。找不到 persona 的 ESRCH 路径恢复为原始源码，
但本轮没有使用有管理权限的进程单独覆盖该运行时分支。既有 AMFI stand-in 从二进制中读取
未经认证的 entitlement，完整签名信任链仍未实现，因此不能把本修复称为完整提权防护或 iPhone 安全等价。

Python 回归 **99 项通过**。证据：

- `out/lemonades/persona-verification/initial/result.json`、`serial.log`：动态服务与凭证验证。
- `out/lemonades/persona-verification/mach-regression/`：新内核 Mach/BSD 回归。
- `out/lemonades/persona-root-v1/build.json`：根镜像、编译命令和源码快照。
- `out/lemonades/persona-audit/sources/`：本轮补丁、构建器与相关测试快照。

## 原厂 persona 提供者

已从固定 rootfs 只读提取 `usr/libexec/usermanagerd` 和
`System/Library/LaunchDaemons/com.apple.mobile.usermanagerd.plist`，尚未启动该 daemon。
Mach-O 为 ARM64 ALL；从原厂文件解析到 `com.apple.private.persona-mgmt`、
`com.apple.private.persona.modify`、XPC persona creator/manager 等权限键。
这是内容检查，不是 Apple 签名认证。

原厂 job 发布三个服务：`com.apple.mobile.usermanagerd.xpc`、
`com.apple.mobile.keybagd.UserManager.xpc`、`com.apple.system.libinfo.muser`。
程序参数为 `-t 15`，RunAtLoad 和 OnDemand 为 true；当前 RAM 根盘启动日志跳过了 usermanagerd boot task。

依赖包括 MobileKeyBag、AppleKeyStore、Security、APFS、IOKit、Foundation/CoreFoundation 和 MobileGestalt。
因此下一步需要验证原厂 daemon 的启动条件、配置/数据目录和这些服务依赖；不能只创建一个空 persona
或直接改 UID 来当作初始化完成。原厂 job 还有 `_PanicOnCrash` 配置，导入时应保留并记录其行为。
输入/检查哈希见 `out/lemonades/persona-audit/usermanager-provider.json`。

## 构建证据保护与历史限制

本轮一次未成功修改补丁后的 shell 仍执行了构建，触发旧构建器的同输入覆盖问题。
已中断该次构建，旧 `f16e35ce0e0407db` 的 stripped kernel 经 SHA-256 验证未变，
但其 `build.json`、构建日志及部分中间文件已被重写。**未能按原哈希恢复历史 manifest 字节**；
当前旧记录标为 interrupted，不能再作为完整构建证明或传给要求成功 manifest 的 runner。
旧 QEMU 日志、结果和源码快照仍在，原 kernel 哈希也仍匹配；不宣称其它构建中间文件未变。

`build-native-kernel.py` 现在只复用输入一致、status=complete、make_exit_code=0 且 kernel
哈希匹配的结果，不重写报告；输入变化、损坏或未完成的已有记录直接拒绝并保留。
prepared 状态可继续真正构建。回归覆盖了复用、损坏拒绝及未完成记录保护。
事件完整记录：`out/lemonades/persona-audit/provenance-incident.json`。
后续复现使用新构建键 `a336b7dfe69cbf78`。

```sh
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/dynamic-smoke.py \
  --root-manifest out/lemonades/persona-root-v1/build.json \
  --build-manifest out/lemonades/native-deps/build/a336b7dfe69cbf78/build.json \
  --output out/lemonades/persona-verification/another-run
```

输出须使用新目录。没有连接手机、刷写或进行实机性能测试。
