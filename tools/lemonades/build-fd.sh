#!/usr/bin/env bash
# Native macOS cross-build of the isolated UEFI tree. No packaging/device access.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
build_tree=${1:-"$root/out/lemonades/mu-build"}
cd "$build_tree"
export WORKSPACE="$PWD"
export EDK_TOOLS_PATH="$WORKSPACE/Mu_Basecore/BaseTools"
export CONF_PATH="$WORKSPACE/Conf"
export PYTHON_COMMAND="$root/out/lemonades/mu-venv/bin/python"
export PACKAGES_PATH="$WORKSPACE/Platforms/OnePlus:$WORKSPACE/Common/Mu:$WORKSPACE/Common/Mu_OEM_Sample:$WORKSPACE/Mu_Basecore:$WORKSPACE/Silicon/Qualcomm:$WORKSPACE/Silicon/Silicium:$WORKSPACE/Silicium-ACPI:$WORKSPACE/Silicium-ACPI/Platforms/OnePlus:$WORKSPACE/Silicium-ACPI/Silicon/Qualcomm"
toolbin="$WORKSPACE/host-tools"
mkdir -p "$toolbin"
for tool in clang llvm-lib llvm-rc; do
  ln -sf "/opt/homebrew/opt/llvm/bin/$tool" "$toolbin/$tool"
done
ln -sf /opt/homebrew/opt/lld/bin/lld-link "$toolbin/lld-link"
# This pinned BaseTools reads CLANG_BIN for the CLANGPDB AArch64 prefix.
export CLANG_BIN="$toolbin/"
export PATH="$toolbin:$root/out/lemonades/mu-venv/bin:$EDK_TOOLS_PATH/Source/C/bin:$EDK_TOOLS_PATH/BinWrappers/PosixLike:$PATH"
build -p lemonadesPkg/lemonades.dsc -a AARCH64 -b RELEASE -t CLANGPDB -n 8 \
  -D FD_BASE=0x9FC00000 -D FD_SIZE=0x300000 -D FD_BLOCKS=0x300 \
  -D ENABLE_SECUREBOOT=0 -D MEMORY_PROTECTION=TRUE -D SHIP_MODE=FALSE \
  -y "$WORKSPACE/Build/lemonades-report.txt" -Y PCD -Y DEPEX -Y FLASH -Y LIBRARY
"$PYTHON_COMMAND" - <<'PY'
import hashlib, json, os, subprocess
from pathlib import Path
workspace = Path(os.environ['WORKSPACE'])
fd = workspace / 'Build/lemonadesPkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd'
result = {
    'status': 'compiled only; run audit-fd.py separately; no hardware validation',
    'fd_sha256': hashlib.sha256(fd.read_bytes()).hexdigest(),
    'clang': subprocess.check_output(['clang', '--version'], text=True).splitlines()[0],
    'lld': subprocess.check_output(['lld-link', '--version'], text=True).strip(),
    'python_packages': subprocess.check_output([os.environ['PYTHON_COMMAND'], '-m', 'pip', 'freeze'], text=True).splitlines(),
    'target': 'RELEASE_CLANGPDB/AARCH64',
    'defines': {'FD_BASE': '0x9FC00000', 'FD_SIZE': '0x300000', 'FD_BLOCKS': '0x300',
                'ENABLE_SECUREBOOT': '0', 'MEMORY_PROTECTION': 'TRUE', 'SHIP_MODE': 'FALSE'},
}
(workspace / 'build-execution.json').write_text(json.dumps(result, indent=2) + '\n')
PY
