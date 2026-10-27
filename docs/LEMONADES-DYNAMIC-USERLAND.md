# APFS 与动态用户态集成

日期：2026-10-26。目标是验证本地最小 XNU 能否通过 APFS 根文件系统执行 Apple dyld、
iOS libSystem 和动态 ARM64 程序。这是完整 iOS 用户态的一项前置验证，不是 9R 实机验收。
本文记录首次动态启动；后续共享缓存运行时检查和原厂 launchd 结果见
[原厂 launchd 与 bootstrap 集成](LEMONADES-LAUNCHD-BOOTSTRAP.md)。

## 实现

`build_dynamic_root.py` 读取固定 iOS 16.5 / 20F66 的 rootfs 和 OS cryptex 提取记录，
逐文件核对 SHA-256，并将 Apple 文件的 UID/GID/mode 写入 APFS ownership manifest。
单独复制 43 个运行时共享缓存文件，排除仅供符号化的 `.symbols`。
缓存位于 `/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld`。
检查缓存的 arm64 magic，并使用 `otool -arch arm64` 检查 dyld、launchd 和测试程序。

根镜像中的 `/sbin/launchd` 是本项目编译的静态诊断 PID 1；原厂文件另存为
`/sbin/launchd.apple`，没有执行。诊断 PID 1 连接标准输入输出到控制台，fork 后
exec `/bin/dynamic_probe`；子程序检查参数、PID/PPID、uname、malloc 写入/读取和 stdio，
退出值必须为 7。父进程必须通过 wait4 取得该退出值，然后打印完整标记并 exit(0)。

APFS writer 固定在 `dynamic-userland-lock.json` 指定的参考仓库提交，并核对源码 SHA-256。
构建输出包含源码快照、编译命令、输入哈希、架构报告和镜像哈希。Apple 二进制只保留在本地 out/。

`dynamic-smoke.py` 要求成功的内核构建记录和根镜像构建记录，启动前重新核对哈希。
QEMU 使用 7 GiB 私有 guest RAM 映射，将根镜像放在 0xFC000000；loader 自动使用 md0。
没有启用 QEMU 网络或访问手机。临时 guest RAM 和 EFI 启动目录退出后清理；日志和证据保留。

通过条件为：平台和内核标记 → PID 1 → 动态 libSystem 输出 → 子进程退出验证 → 完成标记 →
预期的 PID 1 exit(0) panic。缺失标记、错误顺序、ABI FAIL、意外 panic 均不能算通过。

## 输入和测试工具修正

- HTTPS Range 返回不足请求长度时，丢弃该响应并重新请求同一区间，最多三次；
  ETag 改变、错误区间和超长响应仍立即拒绝。完整组件仍需通过 ZIP CRC 和大小验证。
- 提取工具新增 repeatable `--include`，可以只读提取必要路径；拒绝绝对路径、`..`、
  通过父目录符号链接逃出镜像。叶节点符号链接保留，不跟随读取外部文件。
- OS 缓存重新以源所有权元数据提取至 `os-cache-owned`，不再依赖旧提取结果的宿主文件所有者。

## 复现

以下输出目录必须不存在，避免覆盖前次实验。原厂组件已存在时会重新验证后复用。

```sh
python3 tools/lemonades/fetch_ios.py --component rootfs
python3 tools/lemonades/extract_ios.py rootfs \
  --output out/lemonades/ios165-source/rootfs-core \
  --include usr/lib/dyld --include sbin/launchd \
  --include System/Library/CoreServices/SystemVersion.plist
python3 tools/lemonades/build_dynamic_root.py --output out/lemonades/dynamic-root-v1
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/dynamic-smoke.py \
  --root-manifest out/lemonades/dynamic-root-v1/build.json \
  --build-manifest out/lemonades/native-deps/build/f16e35ce0e0407db/build.json \
  --output out/lemonades/dynamic-verification/initial
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'
```

## 验证状态

**QEMU 集成测试已通过**，证据位于 `out/lemonades/dynamic-verification/initial/`：
`result.json` 保存检查结果、命令和哈希，`serial.log` 保存完整串口输出。
Python 回归 **92 项通过**。本轮没有修改或重新编译内核，沿用 `f16e35ce0e0407db`。

实际输出顺序：

```text
apfs: volume 0 "Dynamic" ... 48 files, 17 directories
DYN INIT v1
DYN PASS libSystem pid=2 kernel=22.5.0 machine=iPhone10,3
DYN PASS child-exit
DYN COMPLETE v1
initproc failed to start -- no exit reason available -- (signal 0, exit status 0 )
```

最后一项是诊断 PID 1 主动正常退出后的预期 panic，仅在前置检查全部通过时接受。
`machine=iPhone10,3` 是研究 loader 配置的身份，不是检测到了一台 iPhone，也不是 9R 实机结果。

- 根镜像：998,715,392 字节，SHA-256
  `85d66b43a1b9d79e60383fa1dbe9bbcbcd298c82fa076e9773926cc44e52e468`。
- 内核 SHA-256：`b7fd70c6aace9ef43e0382b81bb7ac8de82037165bbe503a1f9a7bf52a5967b1`。
- `SystemVersion.plist` 实际确认为 16.5 / 20F66；原厂 dyld 与 launchd 为 ARM64 ALL。

日志保留了初始 `shared_region_check_np` 未找到起始映射、`map_with_linking_np` 的
`not code signed` 提示，以及已有 minimal kernel 的 minisandbox 行为。这次运行确实进入
Apple dyld/libSystem，但尚未单独验证共享区域映射模式、所有子缓存 UUID 或签名安全等价性；
继承内核已有 AMFI/Sandbox stand-in，不构成 iPhone 的完整安全能力验收。

接续工作：直接验证缓存查询与共享区域状态，再接入跨进程 bootstrap 和原厂 launchd 的初始化依赖。
尚未验证真实 launchd、SpringBoard 或任何 9R 外设与实机流畅度。
