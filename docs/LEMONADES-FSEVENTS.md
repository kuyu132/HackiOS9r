# 原厂文件事件服务与缓存刷新差异

日期：2026-10-26。接续 [偏好设置服务](LEMONADES-PREFERENCES.md)。
后续对照：[API 更新、延迟保存与 vnode 通知](LEMONADES-PREFERENCES-REFRESH.md)。
已导入原厂 fseventsd，并在通用 QEMU 中收到真实新建文件的事件回调。
新增的外部偏好文件替换测试仍失败：文件已更新，但同进程 CFPreferences 读取持续返回旧值。
因此当前结果是文件事件链路取得进展，不能宣称完整偏好设置刷新已兼容。

## 已实现与通过的范围

`build_dynamic_root.py --fsevents <tree>` 验证固定 iOS 16.5 rootfs 提取记录、文件哈希与原始权限，
导入 `/usr/libexec/fseventsd` 及 `com.apple.fseventsd.plist`。保留原厂 System session、MachServices、
RunAtLoad/KeepAlive，仅增加诊断输出。没有改写 Apple 二进制或原厂权限判断。

沿用内核 `f6d7409e8d4fa72e`，其实际生成的 `config_fse.h` 为 `CONFIG_FSE=1`，
vfs_fsevents 对象与设备初始化已在构建中。本轮没有重新构建或修改内核。

新增独立 `fsevents_probe.c`，连接原厂 iOS FSEvents.framework：

- 在 RAM 卷建立唯一测试目录，以 SinceNow、NoDefer、FileEvents 创建订阅。
- 成功启动订阅后才新建并写入文件。
- 回调必须包含该文件的完整路径、ItemCreated、ItemIsFile 和有效事件 ID；拒绝丢事件标志。
- 等待最多 10 秒；停止订阅、invalidate，并排空回调队列后释放上下文和清理文件。
  父进程另有约 20 秒的超时杀死/回收保护。

v17 实测收到 `.../created`，flags=`0x11100`，event ID=`2339`；目录事件没有被误判为文件事件。
原厂 fseventsd[7] 在 System 域启动，cfprefsd 原有的 FSEvents lookup / FSEventStreamStart 缺服务错误消失。
bootstrap job exit(0)，再观察 10 秒无 panic。该次测试包含此前的用户身份、会话一致性、RAMFS 和偏好读写检查。

日志检查器增加 FSEVENTS FAIL 拒绝及原厂服务 PID 关联。宿主回归 **112 项通过**，
新增 callback 测试的 11 个场景只使用本地事件数组，不订阅宿主文件系统。

## 尚未通过：外部文件替换后的缓存刷新

新增测试先在同一进程读入旧值，再用普通文件 API 写入新 binary plist 并原子 rename 替换
专用诊断域文件。验证文件内容为新 nonce 后，通过公开 CFPreferencesSynchronize / CopyValue 轮询。
不调用私有 cache reset，不伪造通知，也不重启原厂服务来制造成功。

Apple 的 [CFPreferences 同步文档](https://developer.apple.com/documentation/corefoundation/cfpreferencesappsynchronize(_:))
说明缓存需要同步才能读入外部变化；本实验已执行同步，但仍需区分原厂当前版本行为与本移植的兼容性问题。
文档及一次 QEMU 失败不足以直接归因某个内核接口。

| 镜像 / 运行 | 结果 |
| --- | --- |
| v17 / initial | 文件创建事件、原有偏好 API 测试通过；不包含外部替换测试 |
| v18 / external-refresh | 8 秒内未读到替换后的新值，整体失败 |
| v19 / refresh-observation | 40 秒内仍为旧值；每 5 秒诊断的 synchronized=1；替换前后保存值检查没有报错，整体失败 |

v18/v19 在偏好测试失败后停止，因此这些运行没有执行后面的独立 FSEvents callback probe；
不能用它们的缺少 callback 标记推断文件事件链路退化。v17 的通过结果按其原始检查器保留。
当前构建器默认启用的 FSEvents 配置会要求更严格的外部刷新检查，**最新端到端结果为失败**。

源码检查确认固定 XNU 的 VNOP_RENAME / post_rename 会投递目录 NOTE_WRITE、目标 NOTE_DELETE、
源 NOTE_RENAME；尚未对本次偏好文件路径逐事件追踪。下一步应比较通过偏好 API 的更新与直接文件更新，
检查 daemon 实际监听路径、事件合并/时机以及缓存更新条件，再决定需要修复的层。

## 其他限制

原厂日志为只读根盘选择了 RAM 下的事件日志回退目录；新卷缺 UUID 后初始化新 UUID。
另有 SecTask 查询 kernel_task[0] 的 cs_flags/entitlements 诊断，未通过修改安全接口来隐藏。
未验证历史事件重放、事件日志持久化、事件丢失恢复、多用户隔离、外部存储或真实 9R。
minisandbox/AMFI stand-in 等既有局限仍适用，不能将本轮等同完整 iOS 或设备流畅度达标。

## 证据与复现

- `out/lemonades/ios165-source/fsevents-provider-extraction.json`：只读原厂提取及输入哈希。
- `out/lemonades/fsevents-audit/`：原厂依赖、ABI/常量与内核配置依据。
- `out/lemonades/fsevents-verification/{initial,external-refresh,refresh-observation}/`：三次独立原始结果。
- `out/lemonades/fsevents-verification/verification.json`：产物复核与当前源码快照。

```sh
python3 tools/lemonades/build_dynamic_root.py --mode usermanager \
  --rootfs out/lemonades/ios165-source/rootfs-launchd-users \
  --core-services out/lemonades/ios165-source/core-service-provider \
  --log-helper out/lemonades/ios165-source/logd-helper-provider \
  --preferences out/lemonades/ios165-source/preferences-provider \
  --fsevents out/lemonades/ios165-source/fsevents-provider \
  --output out/lemonades/fsevents-root-new
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/dynamic-smoke.py \
  --root-manifest out/lemonades/fsevents-root-new/build.json \
  --build-manifest out/lemonades/native-deps/build/f6d7409e8d4fa72e/build.json \
  --output out/lemonades/fsevents-verification/new --timeout 120
```

输出使用新目录。此命令包含当前未通过的外部刷新检查；失败没有从验收条件中删除。
