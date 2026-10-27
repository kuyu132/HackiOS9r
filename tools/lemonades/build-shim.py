#!/usr/bin/env python3
"""Build an isolated, payload-free BootShim for the candidate 9R UEFI memory map."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mu', type=Path, default=ROOT / 'Mu-Silicium')
    ap.add_argument('--output', type=Path, default=ROOT / 'out/lemonades/shim')
    ap.add_argument('--fd-base', type=lambda x: int(x, 0), default=0x9FC00000)
    ap.add_argument('--fd-size', type=lambda x: int(x, 0), default=0x300000)
    ap.add_argument('--objcopy', default=shutil.which('llvm-objcopy') or '/opt/homebrew/opt/llvm/bin/llvm-objcopy')
    args = ap.parse_args()
    expected = json.loads(Path(__file__).with_name('sources.json').read_text())['mu']['commit']
    # Read the pinned blob, not an edited BootShim which might copy an unreserved XNUP payload.
    asm = subprocess.check_output(['git', '-C', str(args.mu), 'show', f'{expected}:BootShim/BootShim.S'])
    if (args.fd_base <= 0 or args.fd_base % 4096 or args.fd_size <= 0 or
            args.fd_size % 4096 or args.fd_base + args.fd_size > 2**32):
        ap.error('FD must be page-aligned, nonempty, and below 4 GiB')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'BootShim.S').write_bytes(asm)
    subprocess.run(['clang', '--target=aarch64-linux-gnu', '-c', str(out / 'BootShim.S'),
                    '-o', str(out / 'BootShim.elf'), '-DREQUIRES_KERNEL_HEADER=1',
                    f'-DFD_BASE={args.fd_base:#x}', f'-DFD_SIZE={args.fd_size:#x}'], check=True)
    binary = out / 'BootShim.bin'
    subprocess.run([args.objcopy, '-O', 'binary', str(out / 'BootShim.elf'), str(binary)], check=True)
    metadata = {'target': 'lemonades', 'fd_base': args.fd_base, 'fd_size': args.fd_size,
                'payload_base': None, 'mu_commit': expected,
                'source_sha256': hashlib.sha256(asm).hexdigest(),
                'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    binary.with_suffix('.bin.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'{binary} (candidate addresses, not boot-validated)')


if __name__ == '__main__':
    main()
