# Mach 消息身份与 mobile 偏好隔离

日期：2026-10-26。在现有最小 XNU / 原厂 iOS 16.5 用户态的 QEMU 环境中，
新增跨进程发送者身份检查，并补齐 mobile 的偏好目录及跨用户读写验证。
本轮没有更改内核身份策略、原厂组件或缓存实现。

## Mach 消息身份

`audit_probe.c` 在原厂 launchd 启动的诊断服务中接收两个独立子进程的消息：
一个保持 root，另一个实际执行 setgroups / setgid / setuid 降为 501。
每个子进程分别通过公开 mach_msg API 和直接 mach_msg2 trap 发送消息。
接收方请求 audit trailer，并核对 PID、有效及实际 UID/GID、非零 PID version，
同时检查消息长度、端口、序号、trailer 类型/大小。

正文故意携带伪造的 root 父进程身份；接收方取得的 kernel trailer 仍对应真实子进程。
v23、v24 均得到以下四项结果及 `AUDIT PASS sender-identity`：

| 发送者 | 公开 API | 直接 mach_msg2 |
| --- | --- | --- |
| root 子进程 PID 11 / UID 0 | 匹配实际身份 | 匹配实际身份 |
| 降权子进程 PID 12 / UID 501 | 匹配实际身份 | 匹配实际身份 |

这支持固定源码中 `proc_calc_audit_token` 与 `ipc_kmsg_init_trailer` 的静态分析：
不能由 CONFIG_AUDIT=0 推断消息身份全为零。audit UID/session 与 POSIX UID 不等价，测试没有混淆它们。
公开 mach_msg API 可能内部调用 mach_msg2，本结果不宣称覆盖旧版 Mach trap。
此测试也不验证代码签名、entitlement 真实性或完整系统访问控制。

## mobile 配置目录与跨用户验证

诊断初始化创建 `/private/var/mobile/Library/Preferences`，Library 及 Preferences 目录为
UID/GID 501、0700；这些是实验环境目录策略，并非已还原原厂完整数据卷模板。
每个 mobile 操作先实际降权，再 exec 新进程，设置 HOME=/var/mobile，避免沿用 root 初始化的 CF 客户端状态。

v24 实际完成：

1. root 写入诊断域 `net.hackios9r.preferences-probe` 的值 A，并在父进程缓存。
2. mobile 新进程向相同域写入 B；另一个 mobile 新进程读取 B。
3. 等待并解析真实 mobile plist，确认 UID 501 所有、无组/其他用户写权限、值为 B。
4. root 通过 API 和真实 root plist 仍读取 A。
5. mobile 新进程删除该键，另一个新进程确认不存在；root 缓存仍为 A。

串口出现四个 `PREFS child ... uid=501` 和 `PREFS PASS mobile-isolation`。
这验证同一配置域的两个用户在本场景中的隔离；不证明应用沙箱、所有配置域隔离、
磁盘持久化，或删除后的文件已完成异步保存。

## 证据与未解决事项

- v23：`out/lemonades/audit-verification/initial/`，消息身份检查通过。
- v24：`out/lemonades/mobile-preferences-verification/initial/`，身份与 mobile 隔离检查通过。
- 核验索引：`out/lemonades/mobile-preferences-verification/verification.json`，关联两次运行、
  源码快照、输入清单、内核和镜像哈希；整体状态沿用各次真实结果。
- 内核沿用 `f6d7409e8d4fa72e`；新根镜像为 `usermanager-root-v23` 与 `usermanager-root-v24`。

宿主回归 114 项通过。新增 audit 验证器测试只构造本地消息，不向宿主服务发送 IPC；
保存值测试使用临时文件与显式模拟的 owner，增加 UID 501 / 0 / 502 所有权判定，
实际降权与跨用户服务行为以 QEMU 运行结果为依据。

原有直接文件替换的缓存刷新检查仍单独保留，见
[API 更新与直接文件修改对照](LEMONADES-PREFERENCES-REFRESH.md)。
v23 和 v24 整体均失败于 `preferences external cache refresh timeout`，没有内核 panic。
v24 的 API 更新与 vnode 通知通过；随后 40 秒观察窗口内缓存仍旧，新进程也读旧值。
后续 FSEvents 文件创建及总体完成步骤因前面的失败未执行，不能记作本轮通过。
通过本轮局部检查不构成全部集成通过。真实 9R 启动、完整桌面、硬件驱动和流畅度仍未验证。
后续继续审查服务端缓存/FSEvents 路径和 mobile 服务集成，不以伪造通知或放宽身份检查替代适配。
