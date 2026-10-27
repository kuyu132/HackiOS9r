# RAMFS 原子重命名与会话保存

日期：2026-10-26。接续 [原厂用户会话初始化](LEMONADES-USERMANAGER.md)。
后续服务端验证与日志依赖进展见 [muser RPC 与 logd_helper](LEMONADES-MUSER-XPC.md)。
本轮解决原厂 usermanagerd 在 RAM 数据卷保存会话时遇到的原子交换缺失。
这不提供持久化存储，也不证明完整 iOS 或 9R 实机功能。

## 实现

`xnu/files/bsd/miscfs/ramfs/ramfs.c` 新增 `vnop_renamex`，与普通 rename 共用检查路径：

- `RENAME_SWAP` 在同一 mount mutex 内交换两条目录项指向的节点。两个名字均保留，
  打开的文件描述符和 hard link 保持各自 inode，文件内容不复制。
- 跨父目录移动目录时更新父指针和父目录链接数；双向检查祖先关系，拒绝造成目录环的交换。
- `RENAME_EXCL` 在锁内检查目标存在性，避免使用会覆盖目标的普通 rename 模拟该操作。
- 在锁内重新校验源/目标目录项与 VFS 传入 vnode 是否匹配，拒绝失效的查找结果。
- 发布对应的 volume capability 与 valid 位。未知语义（包括 SECLUDE）继续返回 ENOTSUP。
- 普通 rename 不再对同 inode 的无操作情况错误更新 vnode 名称/父身份。

VFS 权限与 MAC 授权仍由固定 Apple XNU 的 `renameat_internal`、`vn_authorize_renamex_with_paths`
执行；没有加入跳过权限、只返回成功或重写 Apple 用户态二进制的路径。

## 实际测试

新增 `tools/lemonades/userland/ramfs_probe.c`，随 bootstrap 测试服务编译并在 guest RAMFS 内执行。
覆盖内容与 inode 交换、旧文件描述符保持、目标缺失、EXCL 拒绝覆盖、互斥 flags、hard link、
symlink、跨目录非空目录交换、目录与文件交换、双向目录环拒绝、父关系与链接数、普通覆盖后
旧 inode 的打开引用，以及 200 次交换期间另一进程的 1,000 次读取。
并发读取只要求单个文件不缺失且字节完整；不把两次独立读两个名字当作原子快照。

同一 v7 根镜像对照：旧内核 `a336b7dfe69cbf78` 在第一个 swap 返回 ENOTSUP（45）；
新内核 `3b6414190db6af36` 通过全部 rename 检查，原厂初始化日志不再出现
`Failed to atomically swap writing file`。该次整体测试仍因 persona manifest 解析假设不符而失败，
记录保留为 failed，不能以部分阶段通过改写原结果。

后续内核 `f6d7409e8d4fa72e` 增加 capability 发布；两版均完成原生完整构建、导出校验和未定义符号检查。
本轮没有修改 persona 权限函数，沿用已恢复的 Apple 校验。

最终 `f6d7409e8d4fa72e` 内核 SHA-256：
`31f26c419442d66e1a5a512ca13ddd9ef0cb389066fc6b9dbd580aaa1ba53bed`。
v9 根镜像在 `ramfs-verification/final` 通过：capability 查询、全部 rename 场景、通知往返、
无权限 persona 请求拒绝，以及原厂保存文件的内容检查。测试服务 exit(0) 后观察 10 秒无 panic。
Python 回归 **102 项通过**，`git diff --check` 通过。

原厂 v1 persona manifest 的 `UserPersonaDictionary` 以 CFData 存储嵌套二进制 plist，
不能只在外层遍历。最终检查按实际格式解析，校验版本、递归深度、大小、ID 数值范围与唯一性，
并将保存的 ID 集合与内核 SYSTEM/DEFAULT/SYSTEM_PROXY 三类枚举逐项比对：**5 个 ID 完全匹配**。
`persona.kb` 从旧运行的 727 字节变为 1439 字节；`usersession.kb` 为 945 字节。
这验证当前 fresh single-user 场景的 persona ID 集合，不覆盖每个会话字段或所有未来 persona 类型。

宿主回归编译同一 C 解析/比对函数，使用真实 CoreFoundation 与受控内核查询回调，
覆盖有效嵌套数据、旧记录、额外/重复 ID、未知版本、字符串 ID、溢出、空集合、错误返回约定、
超容量和损坏 bplist 共 11 个场景。QEMU 则使用真实内核查询。

## 尚未解决

F_BARRIERFSYNC 仍返回 ENOTTY。RAM 数据卷没有物理持久介质，不能将屏障空返回成功当作数据落盘。
原厂用户管理、日志服务的其它依赖仍见上一阶段文档；本修复不覆盖 APFS 写入、UFS、断电恢复或长期稳定性。
AMFI stand-in、精简 DriverKit/DART/PPL 等原有内核限制仍然适用。

实际运行目录为 `out/lemonades/ramfs-verification/`，每次输出独立保留源码、manifest、串口与结果。
`before` 是旧内核失败对照，`after` 与 `manifest-shape` 保留解析器修正前的失败，`final` 为最终通过。
`verification.json` 记录本轮四次运行的产物核验及源码快照哈希。

```sh
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/dynamic-smoke.py \
  --root-manifest out/lemonades/usermanager-root-v9/build.json \
  --build-manifest out/lemonades/native-deps/build/f6d7409e8d4fa72e/build.json \
  --output out/lemonades/ramfs-verification/new-run --timeout 90
```

输出须为全新目录。没有连接、刷写或测试用户手机。
