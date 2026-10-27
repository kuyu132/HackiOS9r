# 原厂偏好设置服务集成

日期：2026-10-26。接续 [用户管理端点与会话一致性](LEMONADES-NSXPC.md)。
后续已导入 [FSEvents 并取得文件事件回调，但外部替换后的缓存刷新仍失败](LEMONADES-FSEVENTS.md)。
本文 v16 的结果保留为历史阶段记录。
新根镜像 v16 在隔离 QEMU 中运行原厂 cfprefsd，完成独立进程间的配置写入、读取和删除测试。
仍然是最小 XNU、只读根镜像与 RAM 数据卷，没有实机或持久化存储验收。

## 导入与数据目录

从固定 iOS 16.5 rootfs 只读提取：

- `/usr/sbin/cfprefsd`：入口导入 `___CFXPreferencesDaemon_main`，依赖现有 CoreFoundation/libSystem。
- `com.apple.cfprefsd.xpc.daemon.plist`：发布 `com.apple.cfprefsd.daemon`。
- `com.apple.cfprefsd.xpc.daemon.system.plist`：发布 system 端点，保留原厂 System session 限制
  及 `CoreFoundation/CFPreferencesSystemSession` feature flag 对 Disabled 的控制。

`build_dynamic_root.py --preferences <tree>` 校验组件来源、输入哈希和原始所有者/模式，
保留原厂二进制及配置，仅增加诊断输出和 `OS_ACTIVITY_DT_MODE=YES`。
当前实测的是 user/501 域中的常规 daemon，不能据此宣称 system 端点也可用。

诊断 PID 1 在 RAM 卷创建 root 的 `Library/Preferences`，模式 0700，是本实验的访问策略，
不是原厂数据模板权限结论。测试只操作专用 `net.hackios9r.preferences-probe` 域。

## 实际检查与结果

新增 `preferences_probe.c`，通过原厂 CoreFoundation 的 CFPreferences API 操作配置。
父进程为每次运行生成新 nonce，依次启动 4 个独立 exec 子进程，每个最多等待约 10 秒：

1. 写入字符串并 synchronize。
2. 新进程 synchronize，再读取并严格比较类型与 nonce。
3. 新进程删除该键并 synchronize。
4. 新进程 synchronize，再确认键不存在。

写入完成后，父进程另读取 root Preferences 下实际生成的 plist，核对常规文件、root 所有者、
不可被组/其他用户写入、合理大小，以及保存值与本轮 nonce 相等。
因此结果涵盖跨进程 API 行为和 RAM 文件写入，不能仅靠同一进程的缓存通过。
删除验证是经 API 的 fresh-process 读取，尚未独立检查删除后的文件内容。

串口记录原厂 launchd 因 `ipc (mach)` 启动 cfprefsd[16]；测试子进程 PID 为 15、17、18、19。
日志检查器要求原厂 daemon 启动记录中 PID 一致，并要求 `PREFS PASS cross-process`。
其后 bootstrap job exit(0)，观察 10 秒无 panic。前序会话三方核对、RAMFS、persona、通知和 muser RPC
检查继续通过。Python 回归 **110 项通过**，`git diff --check` 通过。

## 当前缺口

日志中原厂 cfprefsd 报告 `com.apple.FSEvents` lookup 失败，随后 `FSEventStreamStart` 失败。
因此配置文件外部修改监听、缓存失效和通知行为尚未接通，不能把本轮称为完整偏好设置兼容。
已从原厂启动表定位下一提供者：`/usr/libexec/fseventsd`，job 为 `com.apple.fseventsd.plist`，
System session，RunAtLoad/KeepAlive，发布 `com.apple.FSEvents`。本轮尚未导入它。

所有读写仍在一次性 RAM 数据卷；未验证 UFS、崩溃一致性或重启后数据保持。
当前继承的 minisandbox/AMFI stand-in 限制仍在，测试不证明原厂沙箱与签名安全等价。
本轮验证一个 root 诊断域，尚未覆盖 mobile/第三方应用域权限、多用户隔离、系统偏好和变更订阅。

## 证据与复现

- `out/lemonades/ios165-source/preferences-provider-extraction.json`：固定来源、文件哈希、权限和只读提取记录。
- `out/lemonades/usermanager-root-v16/build.json`：镜像、编译命令及源码快照。
- `out/lemonades/preferences-verification/initial/`：QEMU 串口、结果和运行工具快照。
- `out/lemonades/preferences-verification/verification.json`：本轮两次运行及当前源码的证据索引。

```sh
python3 tools/lemonades/build_dynamic_root.py --mode usermanager \
  --rootfs out/lemonades/ios165-source/rootfs-launchd-users \
  --core-services out/lemonades/ios165-source/core-service-provider \
  --log-helper out/lemonades/ios165-source/logd-helper-provider \
  --preferences out/lemonades/ios165-source/preferences-provider \
  --output out/lemonades/preferences-root-new
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/dynamic-smoke.py \
  --root-manifest out/lemonades/preferences-root-new/build.json \
  --build-manifest out/lemonades/native-deps/build/f6d7409e8d4fa72e/build.json \
  --output out/lemonades/preferences-verification/new --timeout 120
```

必须使用全新输出目录。本轮沿用已完成内核构建，没有修改原厂组件或实机状态。
