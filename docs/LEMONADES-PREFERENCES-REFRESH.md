# 偏好 API 更新、文件保存与通知的对照

日期：2026-10-26。接续 [FSEvents 与外部刷新差异](LEMONADES-FSEVENTS.md)。
本轮确认原厂 CFPreferences 的 API 跨进程更新可被已缓存旧值的客户端读取；
外部原子替换文件仍不能在 40 秒内被原客户端或新进程读入。最新整体集成结果仍为失败。

## 新增对照与结果

`preferences_probe.c` 增加同一测试域内的独立路径：

1. 父进程先读旧 nonce，形成客户端缓存；新 exec 子进程通过 CFPreferencesSetValue / Synchronize
   写入带 `-api` 后缀的新值。
2. 父进程分别观察自己的 API 读取结果和 RAM 卷上真实 plist 的保存值，要求两者最终同时为新值。
3. 此后才直接写入另一份 binary plist 并原子替换文件，保留已有缓存，执行公开同步/读取。
4. 在文件替换前，以 kqueue 订阅原文件和父目录；要求原文件 NOTE_DELETE 与目录 NOTE_WRITE，
   不能以调用 rename 返回成功代替通知证据。
5. 外部刷新超时后重新核对文件，再启动全新进程通过 CFPreferences 读取，区分旧客户端局部缓存与更广的陈旧状态。

| 镜像 / 运行 | 观察 |
| --- | --- |
| v20 / api-and-vnode | 第二次 API 写入成功后立即核对文件，仍为旧值；整体失败，保留原结果 |
| v21 / api-observation | API 读取已为新值，文件在若干秒后才更新；API 与 vnode 通知通过，直接文件替换仍超时 |
| v22 / fresh-reader | 初次轮询 cache=1/saved=0，第 58 次轮询时两者均为新值；原文件 NOTE_DELETE、目录 NOTE_WRITE；外部替换 40 秒后原客户端仍旧，文件仍新，新进程也旧 |

轮询间隔为 100 ms，但还包含 API/文件操作开销；第 58 次是 QEMU 中的观察，不是 9R 性能指标。
v20 的即时文件断言不足以区分延迟保存与失败，已用有界的独立缓存/文件观察替代。
测试仍必须看到真实文件新值才能通过，未用“API 返回成功”替代保存验证。

v22 串口：

```text
PREFS API refreshed poll=58
PREFS PASS api-live-refresh
PREFS vnode event ident=4 flags=0x21 fflags=0x2
PREFS vnode event ident=3 flags=0x21 fflags=0x1
PREFS PASS external-vnode-events
PREFS external file still matches replacement
PREFS fresh observation matches-external=0 pid=20
BOOTSTRAP FAIL: preferences external cache refresh timeout
```

## 结论边界与后续方向

API 跨进程更新、目录/旧文件的 vnode 通知在当前实验中可用。直接文件替换的旧值问题并非仅原客户端
局部缓存；需要进一步检查服务端/共享缓存、FSEvents 监听路径及直接文件修改在原厂系统的处理条件。
没有以此认定是哪一个内核函数有 bug，也没有通过重启服务、关闭缓存或伪造通知让测试通过。

另只读检查发现当前配置 `CONFIG_AUDIT=0`，但固定 XNU 的 `proc_calc_audit_token` 仍无条件填充
PID/UID 等字段，`ipc_kmsg_init_trailer` 使用 sender task token。不能仅凭关闭审计配置或原厂日志的
kernel_task[0] 诊断，断言所有 Mach 消息的客户端身份都是零。实际消息 trailer 身份可另行验证。

外部直接修改文件与正常应用通过偏好 API 更新是不同场景。本轮已取得后者的运行证据，仍保留前者为未解决问题。
后续应推进 mobile 应用域、服务端观察和跨进程身份验证，避免把不明原因的原厂缓存行为改成无条件读盘。

## 验证与证据

Python 宿主回归 **113 项通过**。新增保存值测试包含 11 组临时文件场景，每组分别验证普通失败输出和
安静的等待中检查，共 22 个子场景；覆盖旧值、错误类型/形状、损坏/空/超大文件、权限、所有者及缺文件。
只读临时 fixture，不联系宿主偏好服务。日志测试同时要求 API 更新、vnode 通知和外部刷新标记完整。
`git diff --check` 通过。

- `out/lemonades/preferences-refresh-verification/{api-and-vnode,api-observation,fresh-reader}/`：三次运行，均保留整体失败结论。
- `out/lemonades/preferences-refresh-verification/verification.json`：构建、镜像、运行产物和源码快照核验。
- `out/lemonades/preferences-refresh-audit/`：范围、调查假设、日志和下一步。

沿用内核 `f6d7409e8d4fa72e`。复现沿用 FSEvents 文档的构建/启动参数，输出目录必须全新。
没有改写原厂组件、关闭其缓存或更改安全策略；真实 9R、持久化存储和完整 iOS 仍未验证。
