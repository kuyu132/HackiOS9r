# 原厂 backboardd 启动与桌面依赖

日期：2026-10-26。接续基础用户态验证，开始导入实际桌面服务。
仍使用最小 XNU 与通用 QEMU；没有在 9R 上运行桌面。

## 原厂输入与接入

从固定 iOS 16.5 / 20F66 rootfs 经只读挂载提取 backboardd、SpringBoard 主程序及启动配置。
记录原始权限、所有者和 SHA-256，提取后卸载本次挂载的磁盘。
backboardd SHA-256：`686f26a6a7b749fd0ae30acca704022da8cb6f85b5c39a0e0e09e25ffd00d273`。
其 46 项直接库依赖中的所有强依赖都在已验证共享缓存的 image 表中；
这不证明递归依赖、资源文件、硬件服务或启动初始化齐全。
SpringBoard 已提取并审查直接依赖，本轮没有启动它。

`build_dynamic_root.py --backboard <desktop-provider>` 导入原厂 backboardd 及 job，
保留 mobile 身份、Interactive 类型、RunAtLoad、KeepAlive 和全部 MachServices。
包括此前缺失的 `com.apple.iohideventsystem`、CARenderServer、显示和背光服务。
仅追加诊断日志设置，不修改 Apple 二进制。

`desktop_probe.c` 调用固定 IOKit 的 IOHIDEventSystemClientCreate / CopyServices，
要求返回非空服务数组。调用方式与 [Apple HID 客户端封装](https://raw.githubusercontent.com/apple-oss-distributions/IOHIDFamily/main/HID/HIDEventSystemClient.m)
的 CopyServices 用法一致；链接符号在固定 SDK 的 IOKit.tbd 中核对。
父进程限制查询子进程运行时间。检查器还要求原厂 backboardd 的匹配 PID 启动记录，
任何 backboardd 退出记录都会使该 profile 失败。
即使该查询通过，也只代表服务枚举，不代表触摸事件、显示、SpringBoard 或整个桌面可用。

## 修正日志重定向造成的启动拒绝

首版把 backboardd 的输出重定向到 `/dev/console`；xpcproxy 报 posix_spawn EACCES，程序未成功 exec。
原厂程序权限为 root:wheel / 0755，并无执行位缺失。

固定 xpcproxy 反汇编在 `0x100004888` 至 `0x1000048a4` 显示 stdout 路径的 addopen flags
为 `0x2020a`，包含 O_RDWR。实测 console 为 UID/GID 0、0622：mobile 可以写，却没有读权限，
不满足这个打开方式。stderr 路径也使用相同 flags。

已把诊断日志改到 `/private/var/mobile/Library/Logs/backboard-bringup.log`，
目录为 mobile:mobile / 0700、文件为 0600，由诊断 PID 1 在 RAM 数据卷创建。
保持 devfs 权限不变，保留原厂身份策略。v2 实测日志文件 UID/GID 501、0600，
原厂 backboardd 成功 exec，证明这一启动阻碍已解除。

## 后续实际失败点

v2 日志显示程序依次执行 CoreAccessories、HID system open/start、GraphicsServices，
进入 window server 初始化后请求 `containermanagerd` 失败。获取
`com.apple.backboardd` 的共享系统容器路径得到 XPC_INVALID_REPLY / error 51，
随后 NSURL 的 nil 路径引发 NSInvalidArgumentException，进程退出并由原厂 KeepAlive 策略重启。
HID 查询返回空结果，未通过。日志中的 “HID system ready” 不能替代端到端功能验证。

依据这个具体失败，进一步只读提取原厂 containermanagerd、containermanagerd_system 及两个 job。
`--containers <container-provider>` 与 backboard profile 一起导入它们，保留原厂
feature-flag 条件参数、Disabled 条件、HostSpecialPort、用户和容器模式，未伪造容器响应。

v3 的容器服务确实启动，但报告 `_installd` 的 `/var/installd` 不存在，紧接初始化日志发生 SIGSEGV。
随后只读检查原厂数据模板，确认该目录为 UID/GID 33、0755，而 `/var/containers` 等根目录在模板中不存在。
已在诊断 RAM 数据卷初始化补齐这个有原厂依据的主目录，容器目录仍由原厂服务处理。
v4 中 bundle owner 的 home 从 `(null)` 变为 `/private/var/installd`，缺目录警告消失，
但 SIGSEGV 仍在；不能将补目录宣称为崩溃修复。
当时尚无精确 fault PC/调用栈。后续已通过 [ICU 数据对照](LEMONADES-ICU.md)
定位日期格式化路径并解除这处容器崩溃；桌面仍因缺原厂事件配置等依赖而失败。

## 运行与证据

| 根镜像 | 运行目录 | 结果 |
| --- | --- | --- |
| backboard-root-v1 | backboard-verification/initial | 重定向与 mobile 权限冲突，启动拒绝；整体失败 |
| backboard-root-v2 | backboard-verification/mobile-log | 原厂程序启动，缺容器服务导致异常；整体失败 |
| backboard-root-v3 | backboard-verification/container-provider | 容器服务执行，缺安装账户目录并发生 SIGSEGV；HID 查询失败 |
| backboard-root-v4 | backboard-verification/installd-home | 安装账户目录已正确解析，容器服务仍 SIGSEGV；HID 查询失败 |

沿用内核 `f6d7409e8d4fa72e`。运行输出位于 `out/lemonades/`，
静态依赖、原厂 job、xpcproxy 反汇编及 staged job 对照保存在 `out/lemonades/backboard-audit/`。
`out/lemonades/backboard-verification/verification.json` 关联四次真实结果，核验内核、镜像、提取输入、源码快照及日志哈希。
四次均未观察到内核 panic，但都未达到 HID 服务检查与完整集成通过条件。
新增日志检查负例覆盖缺 HID 查询结果、缺启动记录、PID 不匹配及服务崩溃；宿主回归 115 项通过。
以前的偏好刷新问题仍未解决，新的 backboard 查询失败会提前结束本 profile，
不能把未执行的后续基础服务检查算作通过。

完整应用容器、窗口服务、显示/HID 设备、SpringBoard 及实机性能仍未完成。
现有 AMFI/沙箱、显示、KeyStore 等研究替代实现的限制继续适用；
原厂程序能开始执行不意味着原厂安全性或硬件功能已复现。
