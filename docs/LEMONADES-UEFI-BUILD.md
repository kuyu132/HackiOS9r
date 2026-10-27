# 一加 9R：完整 UEFI 探针构建

2026-10-25：普通 XBL 与 LP5 两套输入均完成 AArch64 UEFI 编译、链接、压缩和独立拆包核验。
**这些是未经过实机启动验证的诊断 FD，不是 iOS ROM，也不是可直接刷入的 boot 镜像。**

最新后续修订见 [协议与初始化审查](LEMONADES-PROTOCOL-AUDIT.md)。下列哈希保留为首次构建记录；
最新 FD 位于 `artifacts/audit-xbl` 与 `artifacts/audit-xbl_lp5`，包含本轮初始化修正。

## 产物与证据

所有路径相对于项目根目录，二进制位于 Git 忽略的 `out/` 下。

| 输入版本 | 最终 FD | SHA-256 |
| --- | --- | --- |
| 普通 XBL | `out/lemonades/artifacts/xbl/lemonades-probe.fd` | `7a74ddd34b694caad5a715c5f1347c580ce890608659a22443f424390bd57570` |
| LP5 XBL | `out/lemonades/artifacts/xbl_lp5/lemonades-probe.fd` | `e18d05b3897647b00e14c44587b965f5d8ba9b4a67268e7ff1044d227a763512` |

两者均为 **3,145,728 字节**，构建 FD 基址为 `0x9FC00000`。压缩外层 FV 使用约 32% 空间；
内部解压后的 FV 为 5,877,760 字节。内部 FV 自动按所需空间分配，报告中的 99% 使用率
不表示超过外层 3 MiB FD 容量，也不证明运行时内存分配一定成功。

各产物目录下：

- `verification.json`：构建输入版本、所有 overlay 输入哈希、编译器/Python 包版本、
  编译参数、FD 哈希、原厂驱动及 section 哈希、未启用的暂存项。
- `inventory.json`、`modules/`、`lemonades-probe.fd.dump/`：独立拆包后的内容。
- `extractor.log`：UEFIExtract 输出，包括 Volume Top File 警告。

普通和 LP5 构建树分别为 `out/lemonades/mu-build/`、`out/lemonades/mu-build-lp5/`。
构建报告在各树 `Build/lemonades-report.txt`，原始构建日志是
`out/lemonades/fd-build.log` 和 `out/lemonades/fd-build-lp5.log`。

## 本轮修改与验证

1. `prepare-build.py` 从固定 commit 导出独立 Mu 工程，填入已暂存的 9R 输入。
   补齐 OpenSSL、Brotli、libfdt、MIPI Sys-T 和 libspdm 等固定子模块。
   不在参考 checkout 内修改或构建。
2. 应用上游的五项 Mu_Basecore 补丁。修复了 `git apply` 在导出目录中向上发现本项目
   `.git` 后可能跳过补丁的问题：设置仓库搜索边界，并逐项反向 `--check`。
3. 增加原生 macOS 构建入口，使用 LLVM 23.1.3 / LLD 的 CLANGPDB AArch64 工具链。
   正确设置此版本 BaseTools 实际读取的 `CLANG_BIN`，并优先使用已编译的原生工具，
   避免系统 Bash 3.2 不支持上游 wrapper 的负数组索引。
4. `uefi/lemonades/mu-probe.patch` 从 BDS 的强制库依赖中移除 `KernelErrataPatcherLib`。
   该上游库会在 ReadyToBoot 时替换 AllocatePages / ExitBootServices，扫描并修改
   Windows loader 内存；诊断探针不需要它。只改隔离工程，不修改厂商二进制。
5. 使用 UEFIExtract 重新拆包，与 GenFds 的实际 FFS 输入表比较：两套均有 **101 个
   固件文件**，不是 101 个驱动。核对其中 **46 个原厂驱动、4 个原厂 RAW 配置**的全部
   PE32 / DEPEX / RAW 字节，均与各自来源一致。暂存但未启用的 23 项另列，不算文件丢失。
6. 内嵌诊断 EFI SHA-256 为
   `ea444e5e266ffa6781bf17148a784a9a0404690084fa9b0b9524df279240b607`。
   同时检查 BDS 链接报告和最终 BDS PE，确认独立 ProbeBootManager 已进入固件，
   Windows 内存钩子未链接。所有 PE32 section 均为 AArch64。

新增验证器会拒绝错误 FV 长度/头部校验和、被替换的探针、修改过的原厂 section、
重复 GUID、缺失的实际 FFS，以及与构建记录不符的 FD/overlay。
本项目 **36 项测试通过**；两套原生 BaseTools 构建各通过其内置的 **309 项测试**。
LP5 使用新目录从头导出并完整构建，验证了工程准备流程。

## 复现命令

先完成[原厂固件提取与暂存](LEMONADES-STOCK-FIRMWARE.md)。本脚本针对 Apple Silicon
macOS，默认 LLVM 位于 `/opt/homebrew/opt/llvm/bin`、LLD 位于 `/opt/homebrew/opt/lld/bin`。
需要 Python 3.12、make、Git，以及已构建的 UEFIExtract。

```sh
# 根仓库、这些子模块都必须含有 prepare-build.py 中列出的固定 commit。
git -C Mu-Silicium submodule update --init \
  Mu_Basecore Common/Mu Common/Mu_OEM_Sample Silicium-ACPI \
  Silicon/Silicium/OpensslPkg/Library/OpensslLib/openssl
git -C Mu-Silicium/Mu_Basecore submodule update --init \
  BaseTools/Source/C/BrotliCompress/brotli \
  MdeModulePkg/Library/BrotliCustomDecompressLib/brotli \
  MdePkg/Library/BaseFdtLib/libfdt \
  MdePkg/Library/MipiSysTLib/mipisyst \
  SecurityPkg/DeviceSecurity/SpdmLib/libspdm

python3 -m venv out/lemonades/mu-venv
out/lemonades/mu-venv/bin/pip install -r tools/lemonades/requirements-uefi-lock.txt

# output 必须尚不存在；已有构建可直接运行 build-fd.sh。
python3 tools/lemonades/prepare-build.py \
  --overlay out/lemonades/uefi-stock-overlay --output out/lemonades/mu-build
make -C out/lemonades/mu-build/Mu_Basecore/BaseTools -j 8
bash tools/lemonades/build-fd.sh out/lemonades/mu-build
python3 tools/lemonades/audit-fd.py out/lemonades/mu-build \
  --output out/lemonades/artifacts/xbl

# LP5 使用另一套输入和构建目录，避免混用。
python3 tools/lemonades/prepare-build.py \
  --overlay out/lemonades/uefi-stock-lp5-overlay --output out/lemonades/mu-build-lp5
make -C out/lemonades/mu-build-lp5/Mu_Basecore/BaseTools -j 8
bash tools/lemonades/build-fd.sh out/lemonades/mu-build-lp5
python3 tools/lemonades/audit-fd.py out/lemonades/mu-build-lp5 \
  --output out/lemonades/artifacts/xbl_lp5

python3 -m unittest discover -s tools/lemonades -p 'test_*.py' -v
```

审计输出目录也拒绝覆盖；重复验证时指定新目录。FD 哈希用于标识本次产物，不承诺
更换构建路径、时间或工具版本后逐字节可复现。

## 仍需处理的事项

- 上游将 `HwResetSystemLib` 映射到 INF 中声明为 `ResetSystemLib` 的 PSCI 库，构建器
  仍给出类名警告。源码使用相同 ResetSystemLib 头文件，链接成功，但这不能验证实机
  PSCI reset/shutdown 行为。本轮没有为消除警告而改动复位逻辑。
- RELEASE 构建不输出 PDB，上游 make 的 PDB 复制步骤会出现标记为 ignored 的错误；
  本轮成功退出的是完整构建命令，最终 FD 又经过独立拆包核验。原始日志保留这些信息。
- UEFIExtract 提示缺少 Volume Top File，日志保留。验证器另查 FV 头部及实际文件表；
  不把这些检查等同于启动认证或硬件兼容性。
- 保留原厂 DEPEX 字节只证明未被修改，不证明所有协议都能在 Mu 中提供。厂商驱动的
  初始化、存储/NVRAM 写入、充电及 USB 行为，IPC SHM/HYP 和页面池配置仍需审查。
  `ProbeBootManager` 会连接驱动，因此不能把整个 UEFI 称为“只读固件”。
- 未选择实际手机的 XBL/LP5 或 SoC DTB，不生成默认刷机包。尚未在 9R 上执行 UEFI，
  也尚未启动 XNU/iOS。下一阶段先审查驱动依赖与启动链，再做匹配设备上的 stage 0 验证。
