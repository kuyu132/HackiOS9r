#!/usr/bin/env python3
"""Compile the pinned SM8250 v2.1 + lemonades overlay as a reference, not stock firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel', type=Path, default=ROOT / 'sources/kernel-sm8250')
    ap.add_argument('--output', type=Path, default=ROOT / 'out/lemonades/reference-dtb')
    args = ap.parse_args()
    source = args.kernel.resolve()
    expected = json.loads((Path(__file__).with_name('sources.json')).read_text())['kernel']['commit']
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != expected:
        ap.error(f'kernel revision must be {expected}; got {revision}')
    if subprocess.run(['git', '-C', str(source), 'diff', '--quiet', 'HEAD', '--',
                       'arch/arm64/boot/dts', 'include/dt-bindings', 'include/uapi']).returncode:
        ap.error('device-tree source/includes have local changes; pin and review them before building')
    for tool in ('clang', 'dtc', 'fdtoverlay'):
        if not shutil.which(tool):
            ap.error(f'missing tool: {tool}')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    dts = source / 'arch/arm64/boot/dts/vendor'
    for name in ('kona-v2.1', 'kona-lemonades-overlay'):
        preprocessed = output / f'{name}.dts'
        with preprocessed.open('w') as out:
            subprocess.run(['clang', '-E', '-P', '-x', 'assembler-with-cpp', '-nostdinc',
                            '-undef', '-D__DTS__', '-I', str(source / 'include'),
                            '-I', str(dts), str(dts / 'oplus' / f'{name}.dts')], stdout=out, check=True)
        with (output / f'{name}.warnings.log').open('w') as log:
            subprocess.run(['dtc', '-@', '-I', 'dts', '-O', 'dtb', '-o', str(output / f'{name}.dtb'),
                            str(preprocessed)], stderr=log, check=True)
    merged = output / 'lemonades-reference.dtb'
    subprocess.run(['fdtoverlay', '-i', str(output / 'kona-v2.1.dtb'), '-o', str(merged),
                    str(output / 'kona-lemonades-overlay.dtb')], check=True)
    subprocess.run(['dtc', '-q', '-I', 'dtb', '-O', 'dts', '-o', str(merged.with_suffix('.dts')),
                    str(merged)], check=True)
    manifest = {'source': expected, 'soc_variant': 'kona-v2.1', 'board_overlay': 'lemonades',
                'status': 'reference-only, not extracted from or tested on the target phone',
                'sha256': hashlib.sha256(merged.read_bytes()).hexdigest()}
    merged.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{merged}\nREFERENCE ONLY: do not treat this as the phone\'s stock DTB.')


if __name__ == '__main__':
    main()
