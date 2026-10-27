#!/bin/bash
# Build the XNU loader as a freestanding AArch64 UEFI application.
set -e
cd "$(dirname "$0")"
target=${LOADER_TARGET:-default}
flags=()
case "$target" in
  default) output=. ;;
  lemonades)
    output=../out/lemonades
    flags+=(-DHACKIOS_LEMONADES_PROBE=1)
    ;;
  *) echo "unknown LOADER_TARGET: $target" >&2; exit 1 ;;
esac
mkdir -p "$output"
"${CC:-clang}" --target=aarch64-unknown-windows -ffreestanding -fno-builtin -fno-stack-protector -fshort-wchar \
  -mgeneral-regs-only -O1 -Wall -Wextra -Wno-unused-parameter "${flags[@]}" -c loader.c -o "$output/loader.obj"
# /base: UEFI loads an image at its preferred address when that is free. The PE default (0x140000000)
# is in the middle of the phone's largest block of RAM, which XNU needs in one piece.
"${LLD_LINK:-lld-link}" /subsystem:efi_application /entry:efi_main /nodefaultlib /base:0xA1000000 \
  "/out:$output/loader.efi" "$output/loader.obj"
ls -la "$output/loader.efi"
