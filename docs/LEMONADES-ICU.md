# 原厂 ICU 数据与容器服务初始化

日期：2026-10-26。接续 [backboardd 初始化](LEMONADES-BACKBOARD.md)。
本轮在最小 XNU / QEMU 中定位并解除容器服务的一处初始化崩溃，完整桌面检查仍失败。

## 故障定位

`dynamic-smoke.py --trace-user-exceptions` 启用已有的 `systrace=1` 内核诊断。
原始运行记录 containermanagerd 的 EXC_BAD_ACCESS，故障地址 `0x8`。
扣除日志中的共享缓存 slide 后，故障 PC 为 `0x186e5674c`：
`__CFGetNonObjCTypeID+0x58`，从空对象加 8 后执行 `ldar`。
调用链为容器迁移状态初始化 → `NSISO8601DateFormatter init` →
`CFDateFormatterCreateISO8601Formatter` → `CFDateFormatterSetFormat` → 类型读取。

CoreFoundation 的公开函数位置使用固定缓存的 `LC_DYLD_EXPORTS_TRIE` 校准；
仅寻找最近的本地符号会把这两帧误标为其他集合类方法。
反汇编显示 ISO formatter 构造路径把创建结果直接传给 SetFormat，未检查空值。
没有修改这个原厂实现，而是检查导致 formatter 创建失败的运行资源。

## 修复与受控对照

固定原厂共享缓存虽包含 libicucore，之前的精简根镜像却没有 ICU 数据。
从同一 iOS 16.5 / 20F66 rootfs 只读提取并核验：

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `usr/share/icu/icudt70l.dat` | 30447056 | `d2d5f82e30f4c193d48da78604381fa551adab548e2533e1ae6139538336f736` |
| `usr/share/icu/icutzformat.txt` | 3 | `327d09f9e798492441b2a7839e2ce11498c64ae4c36ea98e248b89c5fc3172fe` |

`build_dynamic_root.py --icu <icu-provider>` 校验提取清单和固定来源，
按原始权限/所有者加入这两个文件，并启用 `locale_probe.m`。
`--check-locale` 可单独启用相同检查，用于不添加资源的对照。
检查先要求 CFDateFormatterCreate 返回非空，再调用原厂 NSISO8601DateFormatter，
要求固定参考日期在 UTC 下精确输出 `2001-01-01T00:00:00Z`。
仅创建对象成功、出现失败标记或缺最终结果都不能通过。

| 运行 | 镜像 | 实测结果 |
| --- | --- | --- |
| trace | backboard-root-v4 | 捕获原始容器服务故障栈；整体失败 |
| without-icu | backboard-root-v5 | CF formatter 返回空，检查明确失败；同一容器故障重现 |
| with-icu | backboard-root-v6 | CF formatter 非空，ISO8601 精确输出通过；观测期间无此前容器故障，整体仍失败 |

v5/v6 使用相同检查源码和内核；对照中没有修补 Apple 程序。
增加 ICU 后，backboardd 获得系统容器路径并进入 shader cache、显示枚举与窗口服务初始化。
这只证明本次初始化路径推进，不证明应用容器的全部迁移、权限、持久化或长期稳定性。

## 新的失败点与后续

with-icu 日志记录 backboardd 因缺少
`/System/Library/BackBoard/EventProcessorConfiguration.plist` 抛出
NSInternalInconsistencyException 并 SIGABRT，由 KeepAlive 重启。
HID 查询仍返回空，显示 swap_end 也返回 `e00002d7`，
且有加速度计插件缺失和其他服务连接错误。下一步先导入并审查已证实缺失的原厂配置，
再判断 HID 和显示接口的剩余问题；不能直接将空查询归因于 9R 触屏驱动。
后续已 [接入原厂事件配置并观测到 backboardd 初始化结束](LEMONADES-BACKBOARD-CONFIG.md)，
HID 查询仍失败；以上表格保留本轮历史结果。

没有启动 SpringBoard，没有实际显示输出或触摸交互验证。
桌面检查失败提前结束本 profile，后续 FSEvents/偏好检查没有执行，不能算通过。
三次运行均没有观察到内核 panic，但均保留 `passed=false`。
原有 AMFI/沙箱、IOKit/显示研究替代实现的限制继续适用，手机功能与性能仍未验证。

## 可复现证据

原始日志、结果及运行源码快照：`out/lemonades/container-crash-verification/`。
符号解析脚本、导出表、反汇编及调用栈：`out/lemonades/container-crash-audit/`。
其中 `verification.json` 核验三次运行的输入清单、源码快照、内核、镜像和日志哈希，
保留各次实际失败结果。沿用内核 `f6d7409e8d4fa72e`，本轮无内核重编译。
宿主回归 116 项通过；这不替代运行时桌面检查。
