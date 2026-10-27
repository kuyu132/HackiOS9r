#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
out=out/lemonades/touch-platform
mkdir -p "$out/include/arm" "$out/include/vm" "$out/include/kern" "$out/include/pexpert" "$out/lemonades"
cp common/lemonades/s3908_*.h "$out/lemonades/"
cat > "$out/include/pexpert/device_tree.h" <<'HEADER'
typedef const struct OpaqueDTEntry *DTEntry;
#define kSuccess 0
int SecureDTLookupEntry(DTEntry, const char *, DTEntry *);
int SecureDTGetProperty(DTEntry, const char *, const void **, unsigned int *);
HEADER
cat > "$out/include/arm/machine_routines.h" <<'HEADER'
#include <stdint.h>
#include <stddef.h>
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
vm_offset_t ml_io_map_unmappable(vm_offset_t, vm_size_t, uint32_t);
void ml_io_unmap(vm_offset_t, vm_size_t);
uint64_t mach_absolute_time(void);
HEADER
cat > "$out/include/vm/memory_types.h" <<'HEADER'
#define VM_WIMG_IO 7
HEADER
cat > "$out/include/kern/clock.h" <<'HEADER'
#include <stdint.h>
void absolutetime_to_nanoseconds(uint64_t, uint64_t *);
HEADER
cat > "$out/include/kern/startup.h" <<'HEADER'
#define STARTUP_SUB_KMEM 1
extern int startup_phase;
HEADER
cc=${CC:-clang}
"$cc" -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined \
  -fno-omit-frame-pointer -DKERNEL -I"$out/include" -I"$out" -Ixnu/files/pexpert \
  -Ixnu/files/bsd -Icommon/lemonades common/lemonades/s3908_{report,input,tcm,session,geni,transport}.c \
  xnu/files/bsd/dev/lemonades_touch.c xnu/files/bsd/dev/lemonades_touch_platform.c \
  tools/lemonades/test_touch_platform.c -o "$out/test-platform"
"$out/test-platform"
