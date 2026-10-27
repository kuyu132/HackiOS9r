# S3908 初始化会话与 XNU 接入

后续传输实现和新测试见 [GENI FIFO 接入](LEMONADES-GENI-TRANSPORT.md)；本文保留上一阶段的构建与验证记录。

日期：2026-10-25。这轮补齐了触摸链路中的**命令分包、初始化协商、响应/异步报告分发和错误恢复状态**。
新组件已进入 XNU 实际构建，宿主测试覆盖它与真实 XNU 队列适配源码的组合。
这里的“接入”指软件接口；尚无 GENI I²C、供电、GPIO、IRQ 的实机通信。

## 协议依据与实现范围

依据固定的 [LineageOS SM8250 Syna_tcm_oncell 驱动](https://github.com/LineageOS/android_kernel_oneplus_sm8250/tree/98a7970af93b7e01ee77156e7fa0eb7e059a57f0/drivers/input/touchscreen/oplus_touchscreen/Synaptics/Syna_tcm_oncell)：

- `synaptics_tcm_oncell.h`：命令/状态值、24 字节 identification、48 字节 application info 前缀。
- `syna_tcm_write_message`：首包为 command + u16le payload length，续写包以 `0x01` 开头。
- `syna_tcm_read_message` / continued-read：`A5 code length`、`A5 03` 续读与尾部 `5A`。
- `syna_tcm_dispatch_message`：异步 identify 表示控制器复位，不能作为普通查询响应。
- `syna_tcm_identify` / `get_app_info` / `set_normal_report_config`：身份、应用状态与配置协商。
- `syna_get_touch_points`：应用信息里的 max_x/max_y 是最大坐标值，点数应加 1。

新增 `common/lemonades/s3908_session.c/.h` 是独立实现的有界状态机，无动态分配、系统时钟或硬件 I/O。
没有复制或链接 Linux 驱动实现。普通配置容量暂时只支持 128 字节，触点数支持 1–10；
不支持的能力会明确停止，不自动猜测字段或切换固件。

## 初始化顺序

| 阶段 | 命令 | 成功条件 |
| --- | --- | --- |
| 身份 | IDENTIFY `02` | STATUS_OK、足够长的身份记录、application mode、有效写入上限 |
| 应用信息 | GET_APPLICATION_INFO `20` | 状态 OK、配置容量、触点数、报文容量和坐标范围通过校验 |
| 停止报告 | DISABLE_REPORT `06` + `11` | 空的 STATUS_OK 响应 |
| 配置普通模式 | SET_TOUCH_REPORT_CONFIG `26` | 19 字节已审查描述符补零至 128 字节，成功响应 |
| 回读确认 | GET_TOUCH_REPORT_CONFIG `25` | 描述符及尾部补零与解析器支持的格式一致 |
| 启用报告 | ENABLE_REPORT `05` + `11` | 成功响应后进入 READY |

报告与命令响应可交错。初始化完成前的触摸报告被丢弃，不改变待处理命令；
READY 后才将已确认配置和坐标范围传给事件解析器。控制器报告的写入上限和总线上限取较小值，
即使只有 3 字节一包，也能把配置命令拆成首包和续写包。

通用 `s3908_tcm_begin_message` 支持最多 512 字节 payload，并复用续读重组；
IDLE/BUSY 的长度字段按上游语义忽略，转换为空状态消息。原 touch-only `s3908_tcm_begin`
保留更严格的报文大小限制。所有入口均不能用于串流中任意扫描拼接多条消息。

## 超时、复位和接入契约

- 时间由调用者传入单调毫秒数。每条命令自首个写包起最多等待 1,000 ms；IDLE/BUSY、
  无关报告和继续写包都不续期。应用 booting/updating 最多查询 10 次，重试间隔至少 100 ms。
- 查询响应缺字段、异常状态、配置回读不符、回包早于全部写包完成等情况，停止会话。
- 异步 identify、命令超时、协议/帧错误会撤销 READY，并为所有活动触点发送一次释放。
  已停止或失败的会话不接受迟到响应重新激活。
- 完整触摸帧中的坏触点数据保留原活动状态，不伪造抬起；传输工作线程应在确认断连、
  复位或持续错误时调用 stop/reset 释放触点。READY 的正常静默不是命令超时。
- **TCM 没有事务编号。重新 start 前，调用者必须完成控制器/总线复位或有依据的排空同步。**
  软件无法判别“上一条命令迟到的 OK”和“新命令的 OK”；这里只能禁止自动重试，不能凭状态机消除歧义。
- write API 返回的每个块只能立即、完整写入一次；短写或失败后必须 stop/resync。
  同一工作线程串行执行 write、poll、message，不能从 IRQ 同时调用。
- 续读事务超时、IRQ、定时调度和实际 I²C 读写仍由未来总线工作线程实现。通用重组器本身不计时。

XNU 接口位于 `lemonades_touch.c` / `sys/lemonades_touch.h`：start、write、poll、message、reset。
全部保留 `/chosen/hackios,board=lemonades` 检查，不自动注册硬件或启动工作线程。
旧的已确认配置 frame API 在会话运行/失败时拒绝调用，避免绕过初始化门槛。
当前 9R probe 仍拒绝内核交接。

## 验证与产物

- ASan/UBSan：4,940 组首读长度/写块上限组合完成整个握手；包含控制器上限小于总线上限、
  配置续写、响应续读、异步报告交错和复位释放。
- 负例覆盖：所有 0–47 字节应用信息截断、错误配置、bootloader mode、过多触点、坏触点、
  部分命令发送后的过早响应、重复迟到响应、时钟倒退、应用状态重试耗尽。
- 实际 XNU 队列适配源码在宿主 mock DT/queue 环境下完成六条命令和 down/up 事件；
  redwood 身份拒绝新接口，失败会话不恢复触摸。
- 保留原 100,000 次解码变异检查，全部便携模块以 AArch64 freestanding 编译通过。
- 使用已安装 capstone 的 `out/lemonades/mu-venv/bin/python` 跑完整 Python 回归，60 项通过。
  系统 Python 缺 capstone，不能作为完整套件的解释器。
- 新源码目录 `out/lemonades/xnu-session-src`，完整 make 和符号导出检查通过。
- 构建报告：`out/lemonades/native-deps/build/405f4cafc6a4916d/build.json`。
- 内核 SHA-256：`2c9150791eb3913e8f7720267ee54499e41688567bd25ab060bfd5cb8d12c40e`。
- 本内核通过 QEMU 普通启动及旧机型参数测试，运行到静态进程 1。
  QEMU 不模拟 S3908，本测试不意味着控制器初始化已在硬件上运行。

证据归档在 `out/lemonades/session-verification/405f4cafc6a4916d/`，含两套 QEMU 日志、
实际启动的 loader 副本、测试输出及 `verification.json`。保留最小内核的 DriverKit/DART/PPL
能力限制，见 [原生构建说明](LEMONADES-NATIVE-KERNEL.md)。

```sh
bash tools/lemonades/check-touch.sh
out/lemonades/mu-venv/bin/python -m unittest discover -s tools/lemonades -p 'test_*.py'

# 旧源码目录不会被覆盖；选择一个不存在的目录，或使用本轮已匹配的源码目录。
python3 tools/lemonades/build-native-kernel.py --source out/lemonades/xnu-session-src
PATH="/opt/homebrew/opt/llvm/bin:$PATH" python3 tools/lemonades/kernel-smoke.py \
  --build-manifest out/lemonades/native-deps/build/405f4cafc6a4916d/build.json \
  --output out/lemonades/session-verification/405f4cafc6a4916d/qemu
# 同上加 --exercise-hardware-guards，并使用 qemu-guards 输出目录。
```

仍需完成 GENI I²C 时钟/供电、reset/IRQ、实际报文采集与坐标方向核验，才可开始实机触摸验收。
