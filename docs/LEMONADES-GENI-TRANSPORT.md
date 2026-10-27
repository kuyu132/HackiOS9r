# S3908 GENI FIFO 传输与工作线程接口

日期：2026-10-25。本轮实现了有界的 GENI FIFO 读写后端，并将它与 TCM 重组、初始化会话和
XNU 触摸队列接口连接。**这是已完成资源初始化的控制器所用的传输组件，尚不是可在 9R 自动启动的完整 I²C 驱动。**
没有访问手机寄存器，没有启用时钟、供电或 GPIO，也没有解除 9R probe 的内核交接限制。

## 已核对的硬件与源码依据

继续使用固定版本 [LineageOS SM8250 kernel](https://github.com/LineageOS/android_kernel_oneplus_sm8250/tree/98a7970af93b7e01ee77156e7fa0eb7e059a57f0)。
协议/寄存器依据为 `drivers/i2c/busses/i2c-qcom-geni.c`、`include/linux/qcom-geni-se.h` 和
**`drivers/platform/msm/qcom-geni-se.c`**。同仓库 `drivers/soc/qcom/qcom-geni-se.c` 是另一套接口，
没有拿它替换实际 downstream I²C 驱动所调用的实现。

`tools/lemonades/geni_reference.py` 从固定提交读取源文件，检查本地 24 个寄存器偏移、8 个中断位
及设备树中的 SE13/触摸节点；报告记录源码哈希。寄存器改错会使回归失败。
这些检查只确认证据对应，不能证明硬件当前就绪。

| 项目 | 源码依据中的值 |
| --- | --- |
| 引擎 | QUPv3 SE13，寄存器窗 `0xa94000` / `0x4000` |
| 设备地址 | S3908，7 位地址 `0x4b` |
| 总线引脚 | GPIO 36/37，`qup13` 复用 |
| reset / attention | GPIO 38 / 39；attention 原始 flags 为 `0x2008` |
| GENI 中断 | GIC SPI 358；与触摸控制器的 GPIO attention 分开 |
| 时钟 | `GCC_QUPV3_WRAP1_S5_CLK`、wrapper 1 的 M_AHB / S_AHB |
| 电源 | `pm8150_l13`、`pm8150a_l1`；名为 vdd_2v8 的节点指定 **3,008,000 µV** |

上述地址没有被加入自动 MMIO 映射或启动入口；也没有将 Linux DTB 当作 XNU ADT 使用。

## 新增实现

`common/lemonades/s3908_geni.c/.h`：

- 使用调用者提供的有序 32 位 MMIO read/write 和 barrier 回调，无分配或忙等。
- bind 只读检查 I²C 固件协议、FIFO 可用、非 DMA/GSI、引擎空闲、空 FIFO、32-bit FIFO 宽度、
  8-bit/four-byte packing、中断状态使能和 RX watermark。不满足条件时不写寄存器。
- 固定地址 `0x4b`，单次 1–32 字节、独立 STOP 的读/写。更长 TCM 消息由上层分包。
  不支持 repeated-start、DMA/GSI、固件装载或写入闪存。
- TX 使用实际剩余 FIFO 空间，按小端组装字；RX 检查 word count、剩余空间与完整长度。
  只有字节数完整、CMD_DONE 已出现、引擎不再 active 且 FIFO 空，才报告成功。
- 错误优先于 CMD_DONE；处理 NACK、仲裁、命令和 FIFO 错误。过早 DONE 不能把尚未发送的数据当成成功。
- 一次事务最多 600 ms，随后请求 CANCEL，50 ms 未确认转 ABORT，再等待 50 ms。
  这些是本实现的有界策略，尚未实机调优。恢复也由调用者继续 poll，不能停在取消请求后就释放资源。
- 所有失败均保持错误状态，不自动重发。恢复标志区分 cancel 成功、abort 成功与未确认停止。

`common/lemonades/s3908_transport.c/.h`：

- 串行驱动会话命令、总线事务和 TCM 重组；每次 poll 至多开始一个事务或处理一次完成。
- 使用上游相同的 9 字节初读；续读带 `A5 03` 前缀，单包仍限制为 32 字节。
- 完整逻辑消息最多组装 1,000 ms，防止跨多个短事务无限等待。
- `attention` 是调用者采样后的触摸 GPIO 有效状态，不是 GENI completion IRQ。
- 总线错误、畸形消息、超时或 stop 会释放活动触点；硬件取消仍继续到终态。
- TCM 响应没有事务编号，所以 start/rebind 前仍要求外部复位/重新初始化和有依据的排空同步。
  失败后不自行开始新会话，也不以“空 FIFO”冒充控制器协议已重新同步。

## XNU 接口与资源生命周期

`lemonades_touch_bus_bind`、`lemonades_touch_bus_poll`、`lemonades_touch_bus_stop`
接入现有触摸队列。所有入口检查 lemonades 身份，bind 在任何 MMIO 回调前拒绝其他机型。
绑定后，旧的直接 frame/session 注入接口被禁用，以保持一个会话所有者。
这些函数没有注册硬件服务、建立定时器、安装中断或自动探测。

平台调用者仍须先提供：正确的 device-memory 映射和内存屏障、供电/时钟/pinmux、
已装载且配置完毕的 I²C SE 固件、独占访问权、被平台屏蔽的 GENI IRQ，以及触摸复位/attention 采样。
资源必须一直有效，包括错误恢复阶段。READY 且 attention 未触发时可等待 GPIO；
有待处理事务、会话命令或恢复过程时须持续调度 poll，时间必须单调前进。

**poll 返回错误，不代表硬件已经停下。** 新增 `lemonades_touch_bus_quiesced()`：

- 返回 1：工作已停止，且已知引擎空闲或已确认 cancel/abort 完成。
- 返回 0：仍在运行，或中止后未确认停止，不能据此移除供电/解除映射；需要平台级恢复。
- 负值：没有绑定或不是 lemonades。

`lemonades_touch_reset()` 在总线模式下会请求停止并释放触点；调用者仍须继续 bus_poll。
没有自动清理无法确认归属的硬件，也没有在错误路径重置别的驱动可能正在使用的引擎。

## 验证

- 448 组传输长度（1–32）、FIFO 深度（2–8）和方向组合，含不满 4 字节的尾部。
- 不就绪配置的只读拒绝、错误与 DONE 同时出现、过早 DONE、RX 超额数据、
  cancel 成功、转 abort 成功和二者均未确认的错误状态。
- 模型分别运行 GENI FIFO、S3908 命令/响应端；7 种 FIFO 深度均完成六条初始化命令、配置续写、
  响应续读、触点按下和总线故障释放。
- 同一寄存器模型连接实际 XNU 队列适配源码；错误机型不会触发 MMIO，stop 只释放一次，
  abort 未确认时 `quiesced` 不会误报成功。
- ASan/UBSan 和 AArch64 freestanding 编译通过；原 4,940 组会话组合、100,000 次解码变异继续通过。
- 完整 Python 回归 62 项通过，包含新的固定源码寄存器校验。

新内核构建和 QEMU 证据见本文件末尾的产物记录。QEMU 不模拟 GENI 或 S3908，
它只能验证包含新代码的通用 XNU 仍能启动静态进程 1，不能替代模型测试或实机验收。

```sh
python3 tools/lemonades/geni_reference.py
bash tools/lemonades/check-geni.sh
bash tools/lemonades/check-touch.sh
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'
python3 tools/lemonades/build-native-kernel.py --source out/lemonades/xnu-geni-src
```

下一层仍是实际的 GCC/电源/pinmux/GENI 固件准备、MMIO 回调、GPIO/定时调度与实机日志，
尤其要确认原厂环境是否允许 FIFO 模式；若只有 GSI，当前实现会拒绝接管，不能强制切换冒充适配成功。

## 本轮产物

- 源码目录：`out/lemonades/xnu-geni-src`。
- 完整 make 返回 0，原有导出检查通过；新 FIFO、transport 和 XNU bus 接口均已链接。
- 构建报告：`out/lemonades/native-deps/build/150a0c992e0ef0d2/build.json`。
- 内核 SHA-256：`a7e8b57285cb828183fc5ce77c9efc657232c548ad0d041cbe57d0f4bce1770d`。
- QEMU 普通启动和旧机型参数测试通过，静态进程 1 的预期退出 panic 仍按原测试规则检查。
- 证据目录：`out/lemonades/geni-verification/150a0c992e0ef0d2/`，其中 `verification.json`
  关联新内核、实际运行的 loader、两套日志及测试源码/输出哈希。

```sh
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/kernel-smoke.py \
  --build-manifest out/lemonades/native-deps/build/150a0c992e0ef0d2/build.json \
  --output out/lemonades/geni-verification/150a0c992e0ef0d2/qemu
# 加 --exercise-hardware-guards 并改为 qemu-guards 输出目录可复现另一项检查。
```
