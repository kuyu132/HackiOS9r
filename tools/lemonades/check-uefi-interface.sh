#!/bin/bash
# Compile the probe's BootManager library against real, pinned Mu headers (no firmware link).
set -euo pipefail
cd "$(dirname "$0")/../.."
for entry in \
  'Common/Mu b8d46c71610318e36a661819e1e3c0b8bdda413a' \
  'Mu_Basecore 3c9c7b2e211e62d2a954ad760a36fe05adc43aa3'; do
  read -r path expected <<< "$entry"
  actual=$(git -C "Mu-Silicium/$path" rev-parse HEAD)
  if [ "$actual" != "$expected" ]; then
    echo "Missing/wrong pinned Mu submodule: $path (see docs/ONEPLUS-9R.md)" >&2
    exit 1
  fi
done
mkdir -p out/lemonades
clang --target=aarch64-unknown-windows -ffreestanding -fshort-wchar -fno-builtin \
  -Wall -Wextra -Wno-unused-parameter -Werror \
  -I Mu-Silicium/Mu_Basecore/MdePkg/Include \
  -I Mu-Silicium/Mu_Basecore/MdePkg/Include/AArch64 \
  -I Mu-Silicium/Mu_Basecore/MdeModulePkg/Include \
  -I Mu-Silicium/Common/Mu/MsCorePkg/Include \
  -c uefi/lemonades/ProbeBootManagerLib/ProbeBootManager.c \
  -o out/lemonades/ProbeBootManager.obj
echo 'ProbeBootManager interface compile passed; complete firmware not linked.'
python3 - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, 'tools/lemonades')
import stock_memory
Path('out/lemonades/MemoryMapLib.c').write_text(stock_memory.source(stock_memory.load()))
PY
clang --target=aarch64-unknown-windows -ffreestanding -fshort-wchar -fno-builtin \
  -Wall -Wextra -Wno-unused-parameter -Werror \
  -I Mu-Silicium/Mu_Basecore/MdePkg/Include \
  -I Mu-Silicium/Mu_Basecore/MdePkg/Include/AArch64 \
  -I Mu-Silicium/Silicon/Silicium/SiliciumPkg/Include \
  -c out/lemonades/MemoryMapLib.c -o out/lemonades/MemoryMapLib.obj
echo 'Stock-derived MemoryMapLib interface compile passed; runtime layout unvalidated.'
