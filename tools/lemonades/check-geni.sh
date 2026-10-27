#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
out=out/lemonades/geni
mkdir -p "$out/include/pexpert" "$out/lemonades"
cp common/lemonades/s3908_*.h "$out/lemonades/"
cat > "$out/include/pexpert/device_tree.h" <<'HEADER'
typedef const struct OpaqueDTEntry *DTEntry;
#define kSuccess 0
int SecureDTLookupEntry(DTEntry, const char *, DTEntry *);
int SecureDTGetProperty(DTEntry, const char *, const void **, unsigned int *);
HEADER
cc=${CC:-clang}
"$cc" -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined \
  -fno-omit-frame-pointer -DKERNEL -I"$out/include" -I"$out" -Ixnu/files/pexpert -Ixnu/files/bsd -Icommon/lemonades common/lemonades/s3908_{report,input,tcm,session,geni,transport}.c \
  xnu/files/bsd/dev/lemonades_touch.c tools/lemonades/test_s3908_geni.c -o "$out/test-geni"
"$out/test-geni"
for module in geni transport; do
  "$cc" --target=aarch64-none-elf -std=c11 -ffreestanding -Wall -Wextra -Werror \
    -O2 -Icommon/lemonades -c "common/lemonades/s3908_$module.c" -o "$out/s3908_$module.o"
done
