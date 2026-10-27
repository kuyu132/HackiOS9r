# 原厂 launchd 与 bootstrap 集成

日期：2026-10-26。接续 [动态用户态验证](LEMONADES-DYNAMIC-USERLAND.md)。
本轮将诊断 PID 1 交给原厂 iOS 16.5 / 20F66 launchd，使用原厂 xpcproxy 启动一个
bootstrap 测试服务。它是最小服务集成环境，仍不是完整 iOS 根目录或 9R 实机系统。
后续 [persona 与进程身份验证](LEMONADES-PERSONA.md) 已改用新内核；其中记录了旧构建
manifest 被重写的历史限制。本文运行日志仍保留，后续复现不要使用旧成功构建记录路径。

## 已获得的运行证据

- dyld 的 `_dyld_shared_cache_contains_path` 对 libSystem 返回存在，对虚构路径返回不存在。
- `__shared_region_check_np` 返回 0、errno 0 和非零地址，证明调用时已有共享区域起始映射。
  先前首次检查的警告发生在该状态建立之前；仍未单独审计所有子缓存 UUID。
- libSystem 的 `getpwnam` / `getgrnam` 解析 root、mobile，核对 UID/GID。
- 诊断 PID 1 挂载 RAM 文件系统作为 `/private/var`，创建基础目录，将 tmp 设为 01777，
  随后 exec 原厂 `/sbin/launchd.apple`。Apple 二进制未经修改。
- 原厂 launchd 通过原厂 xpcproxy 启动 `bootstrap_probe`。服务验证 PID > 1、PPID = 1，
  向 launchd check-in，取得 receive right；再 lookup 同一名称，核对同一对象的 send right。
- 对未注册服务的查询返回 BOOTSTRAP_UNKNOWN_SERVICE，临时 send/receive right 清理成功。
  launchd 自身记录测试服务 `exit(0)`；最终 runner 将 PID、spawn、完成标记和退出日志关联起来。
- 完成后继续观察 10 秒，没有 kernel panic。此时间窗不是长期稳定性测试。

本轮 Python 回归 **96 项通过**。没有修改/重建内核，沿用 minimal XNU
`f16e35ce0e0407db`，其既有 AMFI/Sandbox stand-in 等限制仍存在。

## 实际失败与修复

第一次启动已进入原厂 launchd，但因 `unable to resolve 'mobile'` 退出并触发 PID 1 panic。
`passwd` 中虽有 mobile，root 身份的用户查询还需要原厂 `master.passwd`。
[Apple Libinfo 的 file_module.c](https://github.com/apple-oss-distributions/Libinfo/blob/39b70c515baee5b609e7e91693edbd934b6845a1/lookup.subproj/file_module.c#L848)
明确展示了按有效 UID 选择该文件的机制。此参考提交不是 iOS 16.5 的版本等价证明；
补齐原厂文件后，实际用户查询和 launchd 启动验证通过。

该文件为 root:wheel / 0600。普通拥有者检查挂载下无法读取，因此提取工具新增
`--owner-readable`：仅接受明确列出的普通文件，先只读挂载并记录源 UID/GID/mode/size，
卸载后再以独立的只读 noowners 挂载读取内容。源所有权仍取自第一遍，不能用第二遍的
宿主读权限替代；两个挂载都卸载本次 attach 返回的盘。目录、符号链接和路径逃逸均拒绝。
没有修改原厂 DMG 的内容或文件权限。失败的早期提取目录没有完整 manifest，不用于构建。

`build_dynamic_root.py --mode launchd` 增加原厂 xpcproxy、账户文件和一个自建 LaunchDaemon。
`dynamic_init.c` 通过编译开关选择交接；默认 dynamic 模式仍在检查后主动 exit(0)。
launchd 模式禁止任何 panic，不能复用旧 dynamic 模式的预期 PID 1 panic 作为通过条件。

## 证据与复现

- `out/lemonades/launchd-verification/initial`：缺 master.passwd 的真实失败。
- `out/lemonades/launchd-verification/users-fixed`：补齐后通过，完整串口日志包括服务 exit(0)。
- `out/lemonades/launchd-verification/final`：使用关联服务 PID/退出日志的最终 verifier 复跑。
- 根镜像 `out/lemonades/launchd-root-v2/dynamic-root.apfs`，998,739,968 字节，SHA-256
  `5e96415a38fd766ec3106516c67e90d76ecab0cd0761a72a52d5e8d0d5402d8a`。
- 每个构建/执行目录包含命令、源码快照和产物哈希；输入 Apple 文件均在忽略的 out/ 内。

输出目录须为新目录。已有目录保留作为证据，以下命令不可直接覆盖它们：

```sh
python3 tools/lemonades/extract_ios.py rootfs \
  --output out/lemonades/ios165-source/rootfs-launchd-users --owner-readable \
  --include usr/lib/dyld --include sbin/launchd \
  --include System/Library/CoreServices/SystemVersion.plist \
  --include usr/libexec/xpcproxy --include private/etc/passwd \
  --include private/etc/group --include private/etc/master.passwd
python3 tools/lemonades/build_dynamic_root.py --mode launchd \
  --rootfs out/lemonades/ios165-source/rootfs-launchd-users \
  --output out/lemonades/launchd-root-v2
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/dynamic-smoke.py \
  --root-manifest out/lemonades/launchd-root-v2/build.json \
  --build-manifest out/lemonades/native-deps/build/f16e35ce0e0407db/build.json \
  --output out/lemonades/launchd-verification/final
```

## 未完成事项

libignition/launchd 将本次 `rd=md0` 识别为 ramdisk/Restore 环境；不能等同于正常 iPhone 启动。
服务实际位于 `user/501` 域，虽测试 plist 指定 root，仍需继续核验实际凭证、域和 persona。
日志有 `kpersona_find_by_type` 找不到 type 6、未导入目录和其它系统服务缺失。
本轮仅验证与原厂 launchd 的 bootstrap 交互，没有完成两个独立业务进程之间的数据协议测试。

下一步按这些日志推进账户/persona、服务配置与正常启动环境，逐步导入真实服务及桌面依赖。
SpringBoard、9R 启动/外设、完整安全能力、流畅度和日常稳定性仍未验证。
