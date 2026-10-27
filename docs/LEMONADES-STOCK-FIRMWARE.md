# 一加 9R 原厂固件离线提取与适配

记录日期：2026-10-25。已获取原厂固件的选定分区和 UEFI 内容，完成设备树拆分、
驱动暂存与候选内存图修正。**尚未生成经验证可启动的完整 UEFI/iOS 镜像。**

## 固件来源和验证

通过[9R 固件索引](https://yun.daxiaamu.com/OnePlus_Roms/一加9R/OxygenOS%20LE2101_14.0.0.2301(EX01)%20H.30/)
找到[厂商 CDN 下载地址](https://gauss-componentotamanual.allawnofs.com/remove-566192819778b5d05fe940821765358d/component-ota/25/08/16/b3fc45995d0f4291aa3d9761365d51fc.zip)。
包内元数据确认：

- 设备 `OnePlus9R_IND` / `pre-device=OnePlus9R`。
- 版本 `LE2101_14.0.0.2301(EX01)`，OTA ID `LE2101_11.H.30_3300_202508051814`。
- Android 14，安全补丁 2025-08-01，OTA 项目号 **20838**。
- 原 ZIP 5,628,638,108 字节，payload 5,628,631,936 字节。

使用 HTTPS Range 下载选定内容，本次提取传输约 84.1 MB，得到 244,387,840 字节的
16 个分区镜像。没有下载整份 5.63 GB ZIP。检查了 metadata/properties 的 ZIP CRC、
payload header+manifest 的 SHA-256、各非空数据操作的 SHA-256，以及每个最终分区的
完整 SHA-256。manifest 哈希还固定在 `tools/lemonades/firmware-sources.json`。
这些是完整性检查；未验证整个 ZIP/payload 的哈希或厂商签名证书链。

输入为公开印度版参考固件，用户手机的地区、内存类型和当前版本仍未知。
未连接、解锁、刷写或修改手机。

## 已保存的产物

目录相对于项目根目录：

| 路径 | 内容 |
| --- | --- |
| `out/lemonades/stock/LE2101_14.0.0.2301/` | XBL、启动镜像和提取记录 |
| 同目录 `extraction.json` | 原始 URL、ETag、包内元数据、分区清单、完整 SHA-256 和校验状态 |
| 同目录 `analysis/inventory.json` | DTB/DTBO 选择字段、XBL ELF 段、UEFI 文件、内存配置 |
| 同目录 `analysis/xbl/`、`analysis/xbl_lp5/` | 分别提取的 UEFI sections 和 `uefiplat.cfg` |
| `out/lemonades/uefi-stock-overlay/` | 普通 XBL 版本的候选工程、原厂驱动、DTB 候选 |
| `out/lemonades/uefi-stock-lp5-overlay/` | LP5 版本的独立候选工程 |

16 个镜像：`abl`、`boot`、`recovery`、`dtbo`、`imagefv`、`qupfw`、`vbmeta`、
`aop`、`devcfg`、`hyp`、`xbl`、`xbl_config`、`tz`、`uefisecapp`、`xbl_lp5`、`xbl_config_lp5`。
本包没有 `vendor_boot` 分区；DTB 位于 boot v2 的专用段。boot 为 96 MiB，recovery 为
100 MiB；不要用 LineageOS 中 96 MiB 的 recovery 配置反推这份原厂 recovery 的大小。
这些大文件和厂商二进制都在 Git 忽略的 `out/` 下。

## 设备树选择

boot 中有 **22** 棵 DTB，DTBO 镜像有 **19** 个条目，包含多个设备/开发板的树。
匹配 9R 的条件是 `oplus,dtsi_no=20828`：boot 条目 15/16/17 对应 SoC v2.1/v2/v1，
DTBO 条目 17 的 board-id 为 `<0x10008 0>`。虽然 OTA 项目号为 20838，包内的 9R
硬件树明确使用 20828；不能把 OTA 项目号直接当作 DTB 选择字段。

已对三个 SoC 修订版分别用 `fdtoverlay` 合并原厂 base 与 overlay，存为：

```text
Resources/DTBs/candidates/lemonades-00020001.dtb  # kona v2.1
Resources/DTBs/candidates/lemonades-00020000.dtb  # kona v2
Resources/DTBs/candidates/lemonades-00010000.dtb  # kona v1
```

每个候选旁边的 JSON 给出硬件证据。没有自动建立 `Resources/DTBs/lemonades.dtb`，
因为尚未确认手机实际 SoC 修订号。合并成功也不能证明 ABL 会选择该候选。
原厂树确认 GIC `0x17A00000` / `0x17A60000`、S3908、I²C `0x4B`、IRQ 39 / reset 38、
坐标 1080×2400。检查器已适配原厂 `synaptics_20828@4B` 与 LineageOS 节点名不同的情况。

## XBL 和内存布局

两套 XBL 都包含 148 个 UEFI file 记录（含容器和 padding，不能称为 148 个驱动）。
其 `uefiplat.cfg` 字节相同，给出 47 条内存/寄存器区域；但 **84 个 file 的 section 内容不同**，
因此两套驱动保持分离。XBL ELF 段与配置表同时支持 FD 地址 `0x9FC00000`、大小 `0x300000`。

已用提取的事实替换候选工程的 8T 内存图，关键修正如下：

| 区域 | 旧 8T 模板 | 9R 固件证据 / 新候选 |
| --- | --- | --- |
| TZApps | `0x82400000 + 0x09600000` | `0x82400000 + 0x0B400000` |
| PIL | `0x8BF00000 + 0x06500000` | `0x8DA00000 + 0x0AD00000` |
| DXE Heap | `0xB0000000 + 0x04500000` | `0x98900000 + 0x03300000` |
| ramoops | 未单独保留，落在旧 heap 内 | `0xB0000000 + 0x00400000`，Reserved |

同时补入 BOOT INFO、XBL Log Buffer、CPU Vectors 和 MCCC 寄存器范围。
结构化依据保存在 `uefi/lemonades/stock-memory.json`，生成逻辑是 `stock_memory.py`。
新 MemoryMapLib 已用真实 Mu 头文件、AArch64 target、`-Werror` 编译。

仍有明确的初始化差异未解决：原厂 IPC SHM 位于其 unusable-DDR 窗口内，候选暂保留
Mu 原有 HYP reservation，将 IPC SHM 保持保留状态，未创建相互重叠的 RAM 描述符。
原厂 `SecPagePoolCount=0x1800`，Mu 候选仍是 `0x680`，需结合分配器和驱动初始化审查。
配置文件中的内存布局不能替代真实 UEFI memory map，更不能证明 XNU payload 地址可用。

## 驱动暂存状态

从 Mu 固定版本的 8T 包只读取 **INF 文本模板**，按 FILE_GUID 对照这份 9R XBL，
复制它自己的 PE32 和 DEPEX。没有复制 8T 或 POCO 二进制。
两个候选工程分别暂存 **51 个 AArch64 驱动 INF 引用 + 22 项 RAW 引用**。
详细来源和哈希见各工程 `stock-staging.json`。

另有 7 项旧屏幕 XML 的 GUID 在原厂 XBL 中没有匹配。这些引用都处于
`USE_CUSTOM_DISPLAY_DRIVER=1` 条件块，当前配置为 0；它们不构成当前默认分支的文件缺失。
没有为满足模板而伪造这些文件。

厂商驱动保持原样，**尚未应用 Mu 兼容补丁或完整审查协议依赖**。两套完整 FD 已构建成功，
并核验当前启用的 46 个原厂驱动及 4 项 RAW 配置字节一致，详见 [UEFI 构建记录](LEMONADES-UEFI-BUILD.md)。
现有 redwood 的 UFS、TZ、USB 等二进制补丁不能按原偏移直接应用到 9R。
下一步可继续离线做驱动行为审查和兼容补丁定位；实际内存类型、SoC 修订号和
启动结果最终需要手机确认。

## 复现

额外源码位置与固定 commit 见 `tools/lemonades/firmware-sources.json`。
将 schema 仓库放在 `sources/payload-dumper-go/`（只用 `.proto`，无需 Go），
UEFITool 放在 `sources/UEFITool/`，INF 模板放在 `sources/device-binaries-templates/`。
模板仓库可稀疏 checkout `kebab/**/*.inf`，无需获取它的其他设备二进制。

```sh
python3 -m venv out/lemonades/firmware-venv
out/lemonades/firmware-venv/bin/pip install -r tools/lemonades/requirements-firmware.txt
out/lemonades/firmware-venv/bin/python tools/lemonades/fetch-stock.py \
  --partitions xbl,xbl_config,xbl_lp5,xbl_config_lp5,abl,boot,recovery,dtbo,imagefv,vbmeta,aop,devcfg,hyp,tz,qupfw,uefisecapp

cmake -S sources/UEFITool/UEFIExtract -B out/lemonades/uefiextract-build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build out/lemonades/uefiextract-build -j 8
out/lemonades/uefiextract-build/UEFIExtract out/lemonades/stock/LE2101_14.0.0.2301/xbl.img all
out/lemonades/uefiextract-build/UEFIExtract out/lemonades/stock/LE2101_14.0.0.2301/xbl_lp5.img all
python3 tools/lemonades/inspect-stock.py out/lemonades/stock/LE2101_14.0.0.2301

# 使用尚不存在的输出目录；生成器拒绝覆盖工程。
python3 tools/lemonades/prepare-uefi.py --output out/lemonades/uefi-stock-overlay
python3 tools/lemonades/stage-stock.py out/lemonades/stock/LE2101_14.0.0.2301 \
  out/lemonades/uefi-stock-overlay --variant xbl
# LP5 版本用新的输出目录重复上述两步，variant 设为 xbl_lp5。
python3 -m unittest discover -s tools/lemonades -p 'test_*.py' -v
```

UEFIExtract 对 Qualcomm ELF 包装层报告 unaligned volume / missing Volume Top File；
没有据此忽略 payload 哈希，已保留原始提取日志。工具成功解析嵌入 FV、解压 sections 并
输出 GUID/配置。它的解析成功不代表 Qualcomm 启动认证或完整性验证完成。
