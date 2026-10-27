# 原厂 muser RPC 与日志辅助服务

日期：2026-10-26。接续 [RAMFS 会话保存](LEMONADES-RAMFS.md)。
后续主端点验证见 [NSXPC 权限拒绝与前台会话读取](LEMONADES-NSXPC.md)；本文保留当轮结果。
本轮新增实际 RPC 验证并导入 logd_helper；仍为无网络通用 QEMU、RAM 数据卷与最小 XNU，
不是完整 iOS 或 9R 实机验收。

## 从空回复定位模式差异

新增 `userland/muser_probe.c`，使用原厂 Libinfo 的 XPC pipe 协议直接向
`com.apple.system.libinfo.muser` 发请求，不以 bootstrap port 或进程启动代替服务响应。
wire key 与字段类型依据固定 Apple Libinfo
`39b70c515baee5b609e7e91693edbd934b6845a1` 的 `libinfo_muser.h` / `muser_module.c`，
再与当前原厂二进制核对。保留原厂二进制 SHA-256：
`ca0cba10ad90ca78f739b6c3e3f2ebf48ace5af0b70b8bc19fe0fa0383543568`。

初版 v10 收到 `available=true`，但 UID 501 请求返回空字典，整体测试保留为失败。
对原厂 ARM64 指令检查发现：

- `0x10002dd30` 起分发 reqtype；`0x10002de3c` 读取 int64 query，验证当前请求协议一致。
- UID 501 分支在 `0x10002de54` 后检查 daemon 模式及 multiuser commpage。
  `0x10002df70..0x10002df94` 在未启用 multiuser 时可直接跳到空回复，不能把此回复单独归因为服务死锁。
- `0x100066bb0` 调用原厂 `host_get_multiuser_config_flags`；没有替代其返回值。
- `gid=299` 分支 `0x10002d80c` 生成 `systemusers` 组的 ID、名称与成员列表。

最终 v11 实测 multiuser flags=`0x1f5`，未设置 multiuser/secondary-users 位。
测试核对有效 availability 回复、当前模式下 UID 查询的行为，以及真实 group RPC 的
`gr_gid=299`、`gr_name=systemusers`、非空数组成员，并要求字段类型正确。
单用户空 UID 回复单独标记为“未由 muser 提供”，**不算 mobile 账户 RPC 成功**。
已有 files backend 的 mobile 账户查询验证继续保留；本轮没有强制启用多用户模式。

请求运行于新 exec 子进程。父进程最多等待约 20 秒，超时杀死并回收子进程，测试失败；
不会以未返回请求当作成功。宿主回归使用真实 XPC 对象与本地模拟 pipe，完全不联系宿主服务，
覆盖单用户空回复、多用户空回复拒绝、有效账户、错误类型、错误组 ID、空成员、IPC 错误与错误 UID。

## logd_helper 集成

从原厂 `System/Library/xpc/launchd.plist` 确认 job 路径和 Program，随后通过现有只读提取工具取得
`usr/libexec/logd_helper`、`System/Library/LaunchDaemons/com.apple.logd_helper.plist`。
`build_dynamic_root.py --log-helper <tree>` 逐项验证固定 rootfs 来源、文件哈希与原始权限，
保留 `LimitLoadToSessionType=System` 等原厂设置；仅增加诊断 stdout/stderr 与环境变量。

实际 QEMU 中，logd 的 IPC 请求触发原厂 logd_helper[9]，xpcproxy 成功 exec、job 进入 running。
原先 `com.apple.logd_helper` 的 missing lookup 不再出现。
这是依赖解析和启动证据；尚未验证日志内容完整性、轮转、持久化或所有 helper 请求。

另根据 daemon 的实际字符串路径创建 RAM `/var/logs`，并准备有界读取 `usermanagerd.log`。
本次没有读到该日志文件，不宣称日志输出链已完整接通。

## 结果与限制

新根镜像 `usermanager-root-v11` 在原有内核 `f6d7409e8d4fa72e` 下通过：
bootstrap、权限拒绝、notifyd 往返、RAMFS rename、5 个 persona ID 一致性及新增 muser RPC 检查。
测试 job exit(0)，再观察 10 秒无 panic。Python 回归 **103 项通过**，`git diff --check` 通过。

`com.apple.mobile.usermanagerd.xpc` 的自激活 error 37 **仍未解决**。
muser 是同进程发布的另一个端点；本结果不能证明主 NSXPC 用户管理端点全部可用。
原厂 main 在 `0x1000474e8..0x100047504` 按 diagnostics/ephemeral-storage 条件跳过一条会话设置路径，
这是后续正常启动环境分析的静态线索，尚未动态证明当前走了哪条分支。
没有改写 boot mode、硬件身份、commpage 或原厂二进制来让测试通过。

F_BARRIERFSYNC、iohideventsystem、完整系统服务与真实存储仍未完成；实机显示/GPU、触控、无线、
蜂窝、多媒体、功耗与流畅度也仍无验收证据。原有 AMFI stand-in 等限制继续适用。

## 证据与复现

- `out/lemonades/muser-verification/initial/`：v10 的严格 mobile 查询失败，保留原 verdict。
- `out/lemonades/muser-verification/mode-aware/`：v11 的实际 RPC 与 helper 启动记录。
- `out/lemonades/muser-audit/`：scope、原厂导入/装载命令/反汇编、分支定位及来源哈希。
- `out/lemonades/muser-verification/verification.json`：本轮产物核验与实现源码快照。

```sh
python3 tools/lemonades/build_dynamic_root.py --mode usermanager \
  --rootfs out/lemonades/ios165-source/rootfs-launchd-users \
  --core-services out/lemonades/ios165-source/core-service-provider \
  --log-helper out/lemonades/ios165-source/logd-helper-provider \
  --output out/lemonades/muser-root-new
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/dynamic-smoke.py \
  --root-manifest out/lemonades/muser-root-new/build.json \
  --build-manifest out/lemonades/native-deps/build/f6d7409e8d4fa72e/build.json \
  --output out/lemonades/muser-verification/new --timeout 90
```

输出必须使用全新目录。没有连接或刷写手机。
