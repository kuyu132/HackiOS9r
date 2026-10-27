#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
out=out/lemonades/touch
mkdir -p "$out"
cc=${CC:-clang}
"$cc" -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined \
  -fno-omit-frame-pointer -Icommon/lemonades common/lemonades/s3908_report.c \
  tools/lemonades/test_s3908.c -o "$out/test-s3908"
"$out/test-s3908"
"$cc" --target=aarch64-none-elf -std=c11 -ffreestanding -Wall -Wextra -Werror \
  -O2 -Icommon/lemonades -c common/lemonades/s3908_report.c -o "$out/s3908_report.o"
echo "S3908 AArch64 freestanding compile: PASS (this check compiles a standalone object)"
# Stage the same source layout as xnu/apply.sh and mock only external kernel services.
mkdir -p "$out/include/pexpert" "$out/include/sys" "$out/lemonades"
cp common/lemonades/s3908_{report,input,tcm,session,geni,transport}.{c,h} "$out/lemonades/"
cat > "$out/include/pexpert/device_tree.h" <<'HEADER'
typedef const struct OpaqueDTEntry *DTEntry;
#define kSuccess 0
int SecureDTLookupEntry(DTEntry, const char *, DTEntry *);
int SecureDTGetProperty(DTEntry, const char *, const void **, unsigned int *);
HEADER
cat > "$out/include/sys/redwood_input.h" <<'HEADER'
#include <stdint.h>
void redwood_touch_post(uint32_t, uint32_t, uint32_t, uint32_t);
HEADER
"$cc" -std=c11 -Wall -Wextra -Werror -O1 -g -DKERNEL -fsanitize=address,undefined \
  -I"$out/include" -I"$out" -Ixnu/files/pexpert -Ixnu/files/bsd -Icommon/lemonades \
  common/lemonades/s3908_{report,input,tcm,session,geni,transport}.c \
  xnu/files/bsd/dev/lemonades_touch.c tools/lemonades/test_s3908_input.c -o "$out/test-input"
"$out/test-input"
"$cc" --target=aarch64-none-elf -std=c11 -ffreestanding -Wall -Wextra -Werror \
  -O2 -Icommon/lemonades -c common/lemonades/s3908_input.c -o "$out/s3908_input.o"
"$cc" -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined \
  -Icommon/lemonades common/lemonades/s3908_report.c common/lemonades/s3908_tcm.c \
  tools/lemonades/test_s3908_tcm.c -o "$out/test-tcm"
"$out/test-tcm"
"$cc" --target=aarch64-none-elf -std=c11 -ffreestanding -Wall -Wextra -Werror \
  -O2 -Icommon/lemonades -c common/lemonades/s3908_tcm.c -o "$out/s3908_tcm.o"
"$cc" -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined \
  -Icommon/lemonades common/lemonades/s3908_{report,input,tcm,session,geni,transport}.c \
  tools/lemonades/test_s3908_session.c -o "$out/test-session"
"$out/test-session"
"$cc" --target=aarch64-none-elf -std=c11 -ffreestanding -Wall -Wextra -Werror \
  -O2 -Icommon/lemonades -c common/lemonades/s3908_session.c -o "$out/s3908_session.o"
