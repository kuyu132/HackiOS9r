# OnePlus 9R 触控平台映射与资源生命周期

日期：2026-10-26。新增 XNU 原生 MMIO 映射、GPIO attention 采样、时钟/引脚只读检查、
异步停止和解除绑定路径，连接上一阶段的 GENI FIFO/TCM 会话。**当前仍需外部平台层先准备并持有资源，
没有自动启动入口，没有在 9R 实机运行，也不是可刷入的 iOS ROM。**

## 固定源码与地址

依据 [LineageOS SM8250 固定提交](https://github.com/LineageOS/android_kernel_oneplus_sm8250/tree/98a7970af93b7e01ee77156e7fa0eb7e059a57f0)
的 `kona.dtsi`、`kona-pinctrl.dtsi`、`kona-qupv3.dtsi`、`pinctrl-kona.c`、`gcc-kona.c` 和 `clk-branch.c`。
`tools/lemonades/touch_platform_reference.py` 读取固定提交原文，推导地址、核对本地常量并保存来源哈希。
回归包含错误 GPIO bank 的拒绝用例。

| 映射窗口 | 物理起点 | 检查/用途 |
| --- | --- | --- |
| GCC branch | `0x118000` | wrapper1 M_AHB/S_AHB 与 S5 的 CLK_OFF |
| GCC vote | `0x150000` | 窗内 `0x2008` 的 bits 20、21、27 |
| TLMM GPIO36–39 | `0x0f524000` | SOUTH bank，GPIO36/37 qup13、reset38、attention39 |
| GENI SE13 | `0x00a94000` | 已配置 FIFO 引擎的实际读写回调 |

每个窗口均为 `0x4000`，起点兼容 4K/16K 页对齐。
TLMM 基址是 `0x0f000000`，SOUTH 偏移 `0x500000`，GPIO stride 为 `0x1000`；
GPIO36–39 不能按通用 TLMM 基址直接加编号偏移。
这不涉及写入 GCC 共享投票或 TLMM 配置。

## 实现与调用约束

实现位于 `xnu/files/bsd/dev/lemonades_touch_platform.c`，接口位于
`xnu/files/bsd/sys/lemonades_touch_platform.h`。新增 `lemonades_touch_bus_unbind()`，
只能在总线确认停止后清除回调；解除映射后不会留下可调用的旧地址。

1. 平台所有者先建立独占权、电源/互连和时钟保持、引脚配置、被屏蔽的 GENI/触摸 IRQ，
   完成 SE FIFO 准备、触摸复位和 TCM 重新同步。`LTP_REQUIRED` 是内核调用者的契约声明，
   **不是从设备树或几个寄存器就能推导出的硬件就绪证明**。
2. VM 初始化及输入队列初始化完成后，由同一个串行进程上下文 worker 调用 `platform_open()`。
   身份、契约标志或 VM 阶段不符时，不映射、不访问 MMIO。已有总线绑定时拒绝接管。
3. 使用 `ml_io_map_unmappable(..., VM_WIMG_IO)`，避免常规 `ml_io_map` 的永久映射路径。
   按 GCC → TLMM → SE 的顺序检查；前一步失败不会访问后一步硬件。映射或预检失败逆序回收。
   固定 XNU 的映射分配使用 KMA_NOFAIL；宿主注入的零返回测试验证防御性回收，不代表真实内核 OOM 可恢复。
4. MMIO 使用 volatile 32 位访问和 `dsb sy` 屏障。`platform_service()` 使用 XNU 单调时钟，
   从 GPIO39 输入位采样 active-low attention，再驱动既有 GENI/TCM 会话。open 本身不启动 I²C 命令。
5. `platform_close()` 请求停止；未完成时继续调度 service。取消/中止确认后先 unbind，再逆序解除映射。
   事务自身失败也经过同样的回收路径。失败未确认停止则进入 QUARANTINED，保留全部映射并拒绝重新打开。

只有 `platform_state() == LTP_CLOSED` 允许平台所有者释放电源/时钟等资源。
close/service 的负返回值本身不能作为释放依据；成功取消也会保留原来的取消/总线错误码。
隔离状态没有“强制释放”入口，需要未来平台复位路径处理。
所有触控接口必须由同一 worker 串行使用，不能与旧的 raw bus/session API 并发。
本轮提供 service 入口，**尚未创建定时器、线程或 IRQ 服务**。

时钟检查仅要求三个 APSS vote 位和 CLK_OFF 清零，不能验证源时钟频率、稳压器或独占归属。
对硬件自动门控也采用保守拒绝策略，不能据此断言设备不兼容。
引脚检查要求 qup13 复用、reset GPIO 输出高和 attention GPIO 输入；不执行复位脉冲或修改上下拉。

## 验证与产物

- 宿主 ASan/UBSan：编译实际平台适配、XNU bridge、GENI、TCM 和 session；仅替换 OS 映射/时间/DT/队列服务。
  覆盖身份/VM/契约检查、四阶段映射失败、六种时钟拒绝、六种引脚拒绝、FIFO 配置拒绝，
  open 不写 SE、TX 完成后 GPIO active-low 触发 RX、NACK 自动回收、空闲关闭、cancel/abort 回收和失败隔离。
  寄存器内存由测试驱动，不是电气模型；释放映射使用真正 free，使 sanitizer 能检查悬空访问。
- 既有 448 组 FIFO 组合、7 种深度的完整初始化、4,940 组会话组合、100,000 次解码变异通过。
- Python 回归 **64 项通过**，含固定源码地址推导和错误 bank 拒绝。
- 完整原生 XNU make 返回 0，导出检查通过，新增 platform/unbind 符号已链接。
  首次构建暴露 BSD 对 Mach 私有映射声明不可见的问题，已按固定声明补齐，未全局扩大私有宏。
- 构建报告：`out/lemonades/native-deps/build/f16e35ce0e0407db/build.json`。
- 内核 SHA-256：`b7fd70c6aace9ef43e0382b81bb7ac8de82037165bbe503a1f9a7bf52a5967b1`。
- QEMU 普通/旧机型参数启动结果与验证索引：`out/lemonades/platform-verification/f16e35ce0e0407db/`。
  QEMU 只验证通用最小内核可达静态 PID 1；该程序预期退出后的 panic 由测试明确检查。
  QEMU 不模拟本轮的 SM8250 寄存器或 S3908。

```sh
python3 tools/lemonades/touch_platform_reference.py
bash tools/lemonades/check-touch-platform.sh
bash tools/lemonades/check-geni.sh
bash tools/lemonades/check-touch.sh
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'
python3 tools/lemonades/build-native-kernel.py --source out/lemonades/xnu-platform-src
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/kernel-smoke.py \
  --build-manifest out/lemonades/native-deps/build/f16e35ce0e0407db/build.json \
  --output out/lemonades/platform-verification/f16e35ce0e0407db/qemu
# 第二组增加 --exercise-hardware-guards，并将输出目录改为 qemu-guards。
```

后续仍需实现平台资源提供者（电源/互连/时钟率、GENI 固件/FIFO 初始化、引脚与 IRQ 归属）、
受控复位/重新同步、串行调度和实机日志，再考虑启用自动触控入口。9R probe 的 XNU 交接仍然关闭。
