# Mach IPC 与 iOS 用户态输入准备

日期：2026-10-26。长期目标继续进行中。本轮推进静态 Mach IPC 验证和真实系统组件导入，
尚未运行 launchd、backboardd、SpringBoard 或完整 iOS，没有实机性能数据。
本文为该轮历史记录；rootfs 下载、带所有权缓存提取与动态启动的后续结果见
[APFS 与动态用户态集成](LEMONADES-DYNAMIC-USERLAND.md)。

## Mach 用户态测试

`tools/lemonades/userland/mach_probe.c` 在通用 QEMU 内实际执行：

- 获取当前 task 端口，创建 server/reply receive right 和 server send right。
- 通过 `mach_msg2` 发送请求，传递 `MAKE_SEND_ONCE` reply right，核对接收端的 header、权限类型和载荷。
- 使用 `MOVE_SEND_ONCE` 回应，验证 reply 队列的数据、端口和 ID；空队列返回 `MACH_RCV_TIMED_OUT`。
- 总计 65 轮创建、请求/回复和清理。此测试覆盖同一任务内的两个用户消息队列，不是跨进程 bootstrap。
- 使用 SDK 生成的 MIG 消息类型，向真实 kernel task port 发送 `task_info`（3405），
  校验返回 ID 3505、NDR、计数、返回码和非零内存统计。
- 完成后继续运行上一轮 BSD identity、errno、VM、fork/pipe/wait4 和 COW 测试。

队列消息使用 `MACH64_SEND_MQ_CALL`，kernel RPC 使用 `MACH64_SEND_KOBJECT_CALL`。
不以 BSD carry/errno 约定解释 Mach 返回值。所有等待有 timeout；没有用放宽内核检查的 boot-arg。

### 实际发现的兼容性问题

首轮使用旧 `mach_msg` 发送时出现 `kGUARD_EXC_INVALID_OPTIONS`，消息 ID 为 `0x3908`。
固定 XNU 的 `osfmk/ipc/mach_msg.c:mach_msg_legacy_allowed` 明确拒绝 platform binary 的旧发送入口。
改用 `mach_msg2` 后通信通过；没有打开 `allow_legacy_mach_msg` 或修改该策略。

第二轮试图释放 task-self control right 时失败。`ipc_right.c` 对 pinned port 最后一个 uref 的
释放返回 `KERN_INVALID_CAPABILITY`。现在像正常进程运行库一样将 task-self 保留到进程结束，
只回收本测试创建的临时队列和权限。此修正是调用方生命周期处理，不是放宽内核保护。

第一次/第二次失败日志分别保留在 `mach-verification/.../initial` 和 `.../msg2`；
成功的普通启动位于 `.../final`，最终 runner 的硬件参数测试位于 `.../guards`。
后者同时保存测试源码、runner 和所用 Mach SDK 头文件快照，避免后续源码变化造成证据不清。
沿用上一轮内核 `f16e35ce0e0407db`，本轮没有重新编译或改动内核。

## Apple CDN 输入与完整性

`tools/lemonades/ios165-source-lock.json` 固定 iOS 16.5 / 20F66、iPhone10,3/10,6 IPSW URL、
总大小、BuildManifest SHA-256、d22ap Erase identity 及三个 allowlisted DMG 的名称、大小和 CRC。
这是兼容用户态的来源选择，不是声称 9R 具有该 iPhone 身份或可以执行 iPhone 恢复流程。

`tools/lemonades/fetch_ios.py`：

- 复用已有 HTTPS Range/Content-Range/ETag 校验；只请求元数据或明确选择的组件。
- 校验固定 BuildManifest 哈希、版本、产品列表、identity 和 component path；检查 ZIP 元数据。
- 流式解压、检查 CRC/大小并记录 SHA-256；完成前不发布 DMG，损坏流删除本次创建的 partial。
- 已有完整文件必须重新核对哈希；已有不匹配文件或未知 partial 不覆盖。
- SHA-256 用于后续复现；**没有验证 Apple DMG/IMG4 签名链**，ZIP CRC 不是签名证明。

本轮下载完成：

| 组件 | DMG | 解压后字节数 | 状态 |
| --- | --- | ---: | --- |
| App cryptex | `096-03536-083.dmg` | 10,485,760 | CRC/大小验证通过，已只读提取 |
| OS cryptex | `096-04666-078.dmg` | 2,726,297,600 | CRC/大小验证通过，已只读提取 |
| root filesystem | `096-04088-077.dmg` | 4,728,546,953 | 仅核对清单，尚未下载/提取 |

路径为 `out/lemonades/ios165-source/`，Apple 二进制仅保存在被忽略的本地 out 目录。
OS tree 含 44 个 dyld cache 文件：43 个运行时文件和一个独立 `.symbols` 文件；
尚未验证 cache UUID/子缓存引用关系或完成运行时加载。

`extract_ios.py` 使用 macOS APFS 原生只读挂载，复制文件并保留符号链接，完成后卸载本次 attach 返回的虚拟盘。
最终版本开启 `-owners on`，在 extraction manifest 中保存源 UID/GID/mode；宿主复制后的所有者不能代替源所有者。
该版本已对 App cryptex 实际执行（`app-cryptex-owned`）。早期的 `os-cryptex` 提取保存内容哈希，
**尚无源所有权元数据**；制作系统镜像前需要使用最终工具重新提取/采集元数据。
不执行映像中的程序，不使用 extract-all ZIP 路径，也没有挂载手机分区。

### 架构检查发现

`webbookmarksd` 是 FAT Mach-O，同时包含 `arm64` 和 `arm64e`；本机 `otool` 默认只显示匹配宿主的切片。
因此依赖审查显式使用 `otool -arch arm64`，不会因为默认显示 arm64e 就判断它无法用于当前研究路线。
已确认它依赖 `/usr/lib/dyld`、libSystem、UIKit/WebKit 等框架；取得此单个文件并不代表这些依赖已满足。

## 验证与复现

81 项 Python 回归通过，新增 Mach trap/option/MIG 编号检查、日志负例、导入完整性与损坏拒绝、
挂载盘标识/路径检查。完整静态 Mach+BSD 场景在普通及旧机型参数 QEMU 中通过。
证据索引：`out/lemonades/mach-verification/f16e35ce0e0407db/verification.json`。

```sh
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/kernel-smoke.py \
  --program mach --build-manifest out/lemonades/native-deps/build/f16e35ce0e0407db/build.json \
  --output out/lemonades/mach-verification/f16e35ce0e0407db/guards --exercise-hardware-guards
python3 tools/lemonades/fetch_ios.py                         # 仅核对清单
python3 tools/lemonades/fetch_ios.py --component os-cryptex # 已有文件先验证再复用
# output 必须是新的目录；不会覆盖现有提取结果。
python3 tools/lemonades/extract_ios.py os-cryptex --output out/lemonades/ios165-source/os-cryptex-owned
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'
```

下一步：取得 rootfs 中的 dyld/launchd，核对与缓存版本/架构的一致性，准备独立可回滚的根镜像，
从动态 hello 开始验证，再接 launchd/Mach bootstrap。上述结果不能替代 9R 启动、外设或完整安全能力验证。
