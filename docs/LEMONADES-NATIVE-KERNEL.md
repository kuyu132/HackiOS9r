# macOS 原生最小 XNU 构建与运行验证

后续触摸会话组件和新构建证据见 [S3908 初始化会话](LEMONADES-TOUCH-SESSION.md)。
本文保留首次打通构建时的版本与哈希；默认 smoke 输出目录可被后续运行更新，以报告内 build_manifest 为准。

日期：2026-10-25。上一轮缺少 SDK 补充依赖的问题已解决。
**本轮已从源码构建包含机型保护和 S3908 模块的新内核，通过完整 make/导出检查，并在 QEMU 进入进程 1。**
它仍是通用 ARM64 最小研究内核，不是已在 9R 验证过的 iOS 系统或可刷写 ROM。

## 构建链

入口：`tools/lemonades/build-native-kernel.py`。依赖版本、下载 URL 和归档 SHA-256
固定在 `native-deps-lock.json`，新增下载、SDK 补充文件和构建产物全部位于 `out/lemonades/`。
本机 Xcode 和系统 SDK 没有被修改。

- Apple XNU：`c54f35ca767986246321eb901baf8f5ff7923f6a`，对应 `xnu-8796.121.2`。
- AvailabilityVersions、libdispatch、libpthread：沿用仓库 Linux 构建已固定的对应版本。
- Theos SDK：固定 `0222fd5413cf4b9af096f37b4621afa2688572f7` 的 `iPhoneOS16.5.sdk`。
  **该目录中的上游 SDKSettings.json 实际标记为 16.4**；保持原文件，构建显式使用 iOS 16.5 deployment target。
  这是社区补充 SDK，不能称为 Apple 内部 SDK。
- DriverKit 头文件：SHA-256 固定的 macOS 13.3 SDK 中 Kernel.framework；IIG 实现使用本项目原有精简 shim。
- 编译器：本机 Xcode 26.6 的 Apple clang，ARM64 / Cortex-A55 代码生成；这是保守的目标选择，
  不代表已验证每颗 9R CPU 的 ISA/页大小/异常等级。host 工具仍使用本机 macOS SDK。
- 依赖库：从源码编译 `libfirehose_kernel.a`、`libpthread_kext.a`，不是空库占位。

对象目录由输入源码、补丁、编译器版本和构建脚本哈希区分；不会因找到旧内核文件而报成功。
构建报告记录 make 返回码、必需的新模块符号、库和内核 SHA-256。make 非零或有未解析符号均失败。
SDK 的库构建使用文件锁串行化；源码版本不匹配或有修改时，不自动 reset/覆盖。

## 实际编译发现并修复的问题

1. 新增 `hackios_platform.h` 原先没有登记到 pexpert 的头文件导出列表，BSD 驱动实际编译找不到它。
   现在 `xnu/redwood.patch` 明确导出该头文件。
2. Apple clang 原生支持 XNU 类型内建函数时，兼容层没有定义 `XNU_NO_TYPE_BUILTINS`，
   导致 OSData/OSValueObject 的条件表达式编译失败。现在原生路径定义为 0，兼容路径保留 1；两种编译器均有回归检查。
3. 新编译器已删除旧的自动变量初始化确认开关。`native-clang.sh` 只过滤该过时开关及旧版本的
   `-Weverything`/强制警告为错误选项，保留警告输出；没有把编译错误转换成成功。
4. 精简 IIG 和非 Apple 硬件配置不实现部分导出 API，但原导出列表仍宣称提供这些接口。
   新的**显式最小配置**使用 `xnu/native-minimal-exports.patch` 修正声明，并运行原有的全部导出检查。

## 最小配置的能力限制

固定移除的声明记录在 `tools/lemonades/native-minimal-exports.json`：
89 条 IOKit RPC、2 条 Libkern RPC、5 条 Private 和 35 条 Private.arm64，共 131 条。
内容属于未实现的 DriverKit 生成接口，以及 Apple DART/UAT/PPL/硬件代码签名相关功能。
保留有效的别名、通配符导出和所有其他声明；不是运行时扫描到任何缺失符号就自动删掉。
回归测试检查补丁与固定清单完全一致，也不允许该补丁修改构建检查程序或添加假实现。

这**没有实现用户态 DriverKit、Apple DART 或 PPL**。不应拿它作为完整 Apple KPI 的替代。
可用于当前通用 ARM64 bring-up 和 QEMU 最小用户态验证，完整 iOS 服务仍需逐项验证。
共享 `xnu/apply.sh` 默认不应用这份配置专用补丁；只有原生构建入口显式应用。
`xnu/export.sh` 会拒绝把带该补丁的源码树直接导出为共享补丁，防止能力限制意外扩散到其他配置。

## 本轮验收

全新源码目录：`out/lemonades/xnu-native-src`。
最终独立构建目录：`out/lemonades/native-deps/build/9351dcc2b8b7216c/`。

- 完整 make 返回 **0**；KPI/symbolset 检查全部通过。
- `nm -u` 无未解析符号；S3908 解码、续读、状态和 XNU 队列适配函数可在新内核符号表定位。
- 新内核 SHA-256：`0ce95d6509186b05c4180e4b14aa81c2820a803a04e5f73f91977bfbdbf03c83`。
- QEMU 使用新内核、新编译 loader 和静态 hello，到达：`I am process 1, uid 0, console fd 0.`。
- QEMU 额外携带 `touchscreen/buttons/cpufreq/gpu/adreno/display_probe/wifi/wifi_step/adsp/speaker_probe`
  等旧机型参数时仍到达进程 1；验证这些入口的机型保护生效，不能解释为外设功能可用。
- 60 项 Python 回归通过；策略头文件、触摸状态/分包/XNU 队列适配的宿主 sanitizer 检查，
  10 万次触摸解码变异检查和 Apple arm64 boot_args ABI 校验继续通过。

QEMU 日志里的 initproc panic 是上游 hello 主动退出 PID 1 的预期终止；测试要求先出现 PID/UID，
并拒绝其他 panic。新内核 QEMU 报告在 `kernel-smoke-built/result.json`，旧参数测试在
`kernel-smoke-built-guards/result.json`；上一轮预编译内核的基线报告仍保留，不能混用。
S3908 代码已链接，但 QEMU 没有模拟 S3908 总线，不能把宿主注入报文测试算作实机触摸。

## 复现

```sh
# 会按锁文件下载缺失依赖、创建源码目录、导出头文件、编译依赖库和内核。
python3 tools/lemonades/build-native-kernel.py

# 使用构建脚本输出的 build.json；以下是本轮的实际路径。
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/kernel-smoke.py \
  --build-manifest out/lemonades/native-deps/build/9351dcc2b8b7216c/build.json
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/kernel-smoke.py \
  --build-manifest out/lemonades/native-deps/build/9351dcc2b8b7216c/build.json \
  --exercise-hardware-guards
```

输入或编译器变化会生成新的构建目录，以脚本打印路径为准。QEMU 测试仍需要锁定的 userland 源码
和 AArch64 EFI 固件；`--firmware` 可覆盖 Homebrew 默认路径。

## 下一步边界

9R probe 的内核交接仍禁用。尚需完成真实运行时内存图/CPU 能力与 ADT/payload 交接、
GENI I²C/触摸供电与中断、显示接管、UFS/DMA、A650 GPU、网络、音频和电源管理，
以及 launchd/backboardd/SpringBoard 的系统镜像集成。没有执行手机连接、解锁、刷写或分区修改。
