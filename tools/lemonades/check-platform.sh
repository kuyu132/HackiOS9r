#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
out=out/lemonades/platform-tests
mkdir -p "$out/pexpert"
# Mock only the external DT service. The identity decoder and access policy are
# the exact header included by the kernel hardware entry points.
cat > "$out/pexpert/device_tree.h" <<'EOF'
typedef const struct OpaqueDTEntry *DTEntry;
#define kSuccess 0
int SecureDTLookupEntry(DTEntry, const char *, DTEntry *);
int SecureDTGetProperty(DTEntry, const char *, const void **, unsigned int *);
EOF
"${CC:-clang}" -std=c11 -Wall -Wextra -Werror -O1 -g -DKERNEL \
  -fsanitize=address,undefined -I"$out" -Ixnu/files/pexpert \
  tools/lemonades/test_platform.c -o "$out/test-platform"
"$out/test-platform"
echo "Kernel hardware identity policy and DT failure paths: PASS"
