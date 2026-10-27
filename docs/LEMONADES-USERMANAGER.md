# 原厂用户会话初始化与基础服务

日期：2026-10-26。接续 [Persona 校验](LEMONADES-PERSONA.md)。
后续已实现 RAMFS 原子交换，并验证保存的 5 个 persona ID 与内核一致，见 [RAMFS 会话保存修复](LEMONADES-RAMFS.md)。
下文 v1–v6 结果保留该阶段的历史状态与限制。
范围为固定 iOS 16.5 原厂组件在通用 QEMU、最小 XNU 与一次性 RAM 数据卷上的初始化。
完整 iOS、9R 实机、Apple 密钥硬件、数据跨重启持久化及流畅度仍未完成。

## 本轮实现

`build_dynamic_root.py --mode usermanager` 导入原厂 usermanagerd 及其原始 LaunchDaemon，
可通过 `--core-services` 同时导入原厂 logd、notifyd。所有输入来自已有固定 rootfs 的只读提取，
逐个校验 SHA-256、来源 manifest、原始 UID/GID/mode；不修改 Apple 可执行文件。
job 仅增加诊断环境和 stdout/stderr 路径，保留原有参数、MachServices 和 `_PanicOnCrash`。

原厂 launchd 内嵌 boot task 包含 `/usr/libexec/usermanagerd --init`，
但当前 RAM 根盘 Restore 启动跳过该任务。诊断 PID 1 在交给原厂 launchd 前补执行它，
使用原厂 boot-task 的 `XPC_SERVICES_UNAVAILABLE=1`、`XPC_NULL_BOOTSTRAP=1` 环境，要求子进程 exit(0)。
这是有限的启动条件复现，不是完整复原 launchd 的启动任务调度。
原厂任务的 `AllowCrash=true` 未用于放宽测试结果。

RAM 数据目录补充：

- mobile 与 diagnostics 的所有者/模式来自原厂模板的只读观察。
- uuidtext、timesync 和新空日志目录的 `.migrated` 标记参考固定 userland 项目的初始化代码。
- `/private/var/keybags` 为原厂初始化日志确认缺失的输出目录；本测试创建为 root:wheel、0700。
  0700 是实验环境的最小访问策略，**不是从原厂模板测得的模式**；不提供预制会话或 persona 数据。
- logd 以原厂 `_logd` 用户运行，不能打开 root console。改用其拥有的 diagnostics 下的日志文件，
  解决实际观察到的 EACCES，不更改 console 权限。

## 验证方法与发现

新内核仍为 `a336b7dfe69cbf78`，保留上一轮恢复的 Apple persona 权限检查。
测试服务继续检查真实 UID/GID、bootstrap 权利与无权限 persona 请求拒绝。

notifyd 验证由两个独立 exec 的进程完成：父进程注册，子进程设置本次唯一的 64 位状态并发送通知，
父进程既检查通知变化，也读回并比对服务端状态。单独 notify_check 有潜在假阳性，不能作为服务证据。
初版 fork 后直接使用 notify 库失败，已改为 posix_spawn 后在新进程内使用。

persona 验证直接调用原厂 `kpersona_find_by_type`，不以服务端口存在或启动日志代替。
修正测试程序的返回约定误用：固定 Apple `libsyscall/wrappers/persona.c` 明确在成功时返回数量，
不是 0；现在要求返回值与输出数量一致且处于缓冲区容量内。
v5 中的 errno=60 是该误判读取的残留 errno，不能据此判定 persona 查询超时。

新增数据验证读取原厂程序生成的 `usersession.kb`、`persona.kb`：要求 root 所有的非空常规文件、
禁止组/其他用户写入，并由原厂 CoreFoundation 解析为非空字典。
这只验证 RAM 卷上的可读结构，不证明所有字段语义、密钥保护或重启后持久化。

## 实际运行记录

| 根镜像 / 验证目录 | 结果与证据 |
| --- | --- |
| v1 / initial | daemon 启动，但未创建可查询的 system-proxy persona；整体失败 |
| v2 / diagnostics | 增加原厂诊断输出；发现通知/日志服务缺失，仍失败 |
| v3 / core-services | 导入 logd/notifyd；logd 的 console EACCES 与 fork 后 notify 调用失败，整体失败 |
| v4 / core-fixed | 修复日志路径与通知测试；原厂 logd 启动、跨进程通知及状态验证通过，persona 未就绪，整体失败 |
| v5 / boot-task | 原厂 --init 创建 System/Default/Personal persona；缺少 keybags 导致文件写入失败，测试返回约定也有误，整体失败 |
| v6 / state-files | 限定的 smoke 通过：两份文件解析、persona count=2（首个 ID=200）、跨进程通知、凭证拒绝与测试 job exit(0)，之后观察 10 秒无 panic；原子更新仍失败，见下文 |

以上目录位于 `out/lemonades/usermanager-root-vN/` 和 `out/lemonades/usermanager-verification/`。
每次实验保留独立根镜像 manifest、源码快照、串口、结果和哈希；失败记录保留原结论。
原厂启动任务摘录：`out/lemonades/persona-audit/launchd-usermanager-boot-task.json`。
本轮 Python 回归 **101 项通过**，`git diff --check` 通过。

**v6 不是会话初始化全面通过。** 日志显示 RAMFS 不支持第二次保存所需的原子交换
（Operation not supported，45），F_BARRIERFSYNC 也返回 ENOTTY（25）。两份可解析文件
分别为 817 和 727 字节、0644，可能保留第一次保存的状态；父目录为 0700。
文件存在/可解析及内核 persona 枚举的 smoke 通过不代表最终 manifest 已保存所有 persona。
已定位 `xnu/files/bsd/miscfs/ramfs/ramfs.c` 仅注册普通 `vnop_rename`、未实现 `vnop_renamex`；
下一步应实现并测试 RAMFS 原子交换语义，再验证最终文件内容与内核 persona 一致。
不能以让 rename/fsync 空返回成功代替真实文件系统操作，也不能把 RAMFS 屏障支持当作持久化能力。

当前已知未解决事项包括原厂 usermanagerd 的自服务激活 error 37、logd_helper 和 iohideventsystem
尚未导入，以及早期 --init 尚无 notifyd 的 generation_changed 通知失败。
进程启动或 persona 枚举不证明这些服务的全部业务请求正常。
内核精简配置和 AMFI stand-in 的限制继续适用，不能据此宣称 iPhone 安全等价。

## 复现

```sh
python3 tools/lemonades/build_dynamic_root.py --mode usermanager \
  --rootfs out/lemonades/ios165-source/rootfs-launchd-users \
  --core-services out/lemonades/ios165-source/core-service-provider \
  --output out/lemonades/usermanager-root-new
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/dynamic-smoke.py \
  --root-manifest out/lemonades/usermanager-root-new/build.json \
  --build-manifest out/lemonades/native-deps/build/a336b7dfe69cbf78/build.json \
  --output out/lemonades/usermanager-verification/new --timeout 90
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'
```

输出必须使用全新目录，验证程序不连接或刷写手机。
