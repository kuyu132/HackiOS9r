# 一加 9R S3908 触摸协议组件

代码：`common/lemonades/s3908_report.c` / `.h`。
这是独立编写、无 I/O、无动态分配的报文解析组件。现已补充续读重组、触点状态和 XNU 队列适配源码，
并已在新的最小通用 XNU 中编译、链接；**尚未完成总线接入或实机触屏读取**。
现已补齐命令会话、初始化协商与报告分发，见 [触摸会话实现](LEMONADES-TOUCH-SESSION.md)。
后续已增加 [GENI FIFO 与工作线程接口](LEMONADES-GENI-TRANSPORT.md)，仍未完成实机资源初始化。
构建结果见 [原生内核验证](LEMONADES-NATIVE-KERNEL.md)。接口细节见
[本轮实现与验证范围](LEMONADES-KERNEL-OFFLINE.md)。

协议依据是固定版本的
[LineageOS Syna_tcm_oncell 驱动](https://github.com/LineageOS/android_kernel_oneplus_sm8250/tree/98a7970af93b7e01ee77156e7fa0eb7e059a57f0/drivers/input/touchscreen/oplus_touchscreen/Synaptics/Syna_tcm_oncell)：
`synaptics_tcm_oncell.c` 中的 `syna_set_normal_report_config`、`syna_parse_report`、
`syna_read_message` 和对应 `.h` 的协议枚举。没有将 Linux 驱动源文件复制或链接进 XNU。
9R DTS 给出最多 10 个触点，I²C 地址 `0x4B`，GPIO IRQ 39 / reset 38。

## 支持的输入

`s3908_decode_normal` 必须同时收到：

1. 经 `GET_TOUCH_REPORT_CONFIG` 确认的普通模式配置。支持这段 19 字节描述符，
   或其后补零至最多 128 字节的形式；不能仅因芯片型号相同而假定固件默认配置相同。
2. 一个已完成 TCM 分包重组的逻辑报文：`A5 11 <payload_length:u16le> <payload> 5A`。
   长度必须准确；传输层的 predictive-read 尾部、多报文和 `A5 03` continuation chunk
   由 `s3908_tcm` 重组组件处理，不能直接交给此解析器；GENI FIFO 后端已实现并经模型验证，实际资源初始化和硬件接入仍待完成。

配置字节：

```text
10 08 01 06 04 07 04 08 10 09 10 0B 0C 0C 0C CB 20 03 00
```

payload 开头是 1 字节 gesture，之后是 0–10 个、每个 12 字节的触点记录。

| 触点内偏移 | 编码 |
| --- | --- |
| 0 | 低 4 位为 ID，高 4 位为 classification |
| 1–2、3–4 | X、Y，16 位小端原始坐标 |
| 5–7 | X width 和 Y width，各 12 位，低位优先 |
| 8–11 | edge width Y、edge width X、edge ratio Y、edge ratio X |

classification 支持 lift=0、finger=1、gloved finger=2；其他值返回错误。
输出按 ID 索引，包含 `present_mask` 和排除 lift 的 `active_mask`，不旋转或缩放坐标。
重复 ID、ID ≥10、配置不匹配、长度错误、残缺记录及 padding 错误都被拒绝。
发生错误时不修改调用方的输出，因此不能把坏包误当作“所有手指抬起”。

## 验证

```sh
bash tools/lemonades/check-touch.sh
```

该脚本运行手工编码的协议向量（不是实机抓包）、10 触点、空帧、抬起/手套、
截断和错误数据测试；在 AddressSanitizer/UndefinedBehaviorSanitizer 下进行
100,000 次确定性随机输入与样例变异，再以 `aarch64-none-elf -ffreestanding -Werror` 编译。
产物位于 `out/lemonades/touch/`。这验证了解码逻辑与部分内存安全性质，未验证控制器通信。

## 接入前仍需实现

- QUPv3 FIFO 传输与串行调度已有组件；仍需时钟/供电/pinmux、MMIO、复位及 IRQ 接入，不能复用 redwood 的 Goodix SPI 初始化。
- TCM 响应/报告分发与命令超时已有组件；仍需总线层实现复位/排空同步和续读超时。
- 能力查询与普通 report config 设置/回读状态机已实现；需在真实总线上验证，并接入恢复/休眠后的重新确认。
- 已实现 active mask、down/move/up、显式释放和坏包不改状态；需由串行总线工作线程接入。
- 核对控制器坐标范围和方向；映射组件要求传入确认后的坐标点数，不能假定屏幕分辨率就是控制器范围。

该组件不包含固件更新命令，也没有启动任何硬件读写。
