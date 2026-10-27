#!/bin/bash
# Target compiler only; host setup tools continue to use the native macOS SDK.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
compiler=${XNU_NATIVE_CC:-$(/usr/bin/xcrun --sdk macosx --find clang)}
if [ "${1:-}" = --cxx ]; then
    shift
    compiler=${XNU_NATIVE_CXX:-$(/usr/bin/xcrun --sdk macosx --find clang++)}
fi
args=()
for arg in "$@"; do
    case "$arg" in
        -enable-trivial-auto-var-init-zero-knowing-it-will-be-removed-from-clang) ;;
        # Match BUILD_WERROR=0 for older XNU sources on a newer compiler; retain warnings.
        -Werror|-Werror=*|-Weverything) ;;
        *) args+=("$arg") ;;
    esac
done
exec "$compiler" --target=arm64-apple-ios16.5 -mcpu=cortex-a55 \
    -include "$root/xnu-deps/hostinc/xnu_clang_compat.h" "${args[@]}"
