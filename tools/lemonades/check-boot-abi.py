#!/usr/bin/env python3
"""Compare generated boot_args bytes with compiled declarations from pinned Apple XNU."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
from boot_contract import ROOT, VIRT_BASE, generate, validate_layout, interval

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--source', type=Path, default=ROOT / 'out/lemonades/xnu-integrated-src')
args = ap.parse_args()
commit = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
if commit != 'c54f35ca767986246321eb901baf8f5ff7923f6a':
    ap.error('unexpected Apple XNU revision')
# Take declarations from the immutable commit, not from patched/generated headers.
header = subprocess.check_output(['git', '-C', str(args.source), 'show',
    f'{commit}:pexpert/pexpert/arm64/boot.h'], text=True)
video = re.search(r'struct Boot_Video \{.*?\n\};', header, re.S).group()
boot = re.search(r'typedef struct boot_args \{.*?\n\} boot_args;', header, re.S).group()
plan = json.loads((ROOT / 'common/lemonades/boot-contract-fixture.json').read_text())
stock = json.loads((ROOT / 'uefi/lemonades/stock-memory.json').read_text())
adt, expected = generate(plan, stock)
alloc = validate_layout(plan, stock)
base, end = interval(plan['ram_window'])
source = f'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define BOOT_LINE_LENGTH 608
{video}
typedef struct Boot_Video Boot_Video;
{boot}
_Static_assert(sizeof(boot_args) == 736, "size");
_Static_assert(offsetof(boot_args, deviceTreeP) == 96, "DT pointer");
_Static_assert(offsetof(boot_args, CommandLine) == 108, "command line");
_Static_assert(offsetof(boot_args, bootFlags) == 720, "flags");
int main(void) {{
    boot_args b;
    memset(&b, 0, sizeof(b));
    b.Revision = 2; b.Version = 2;
    b.virtBase = {VIRT_BASE}ULL; b.physBase = {base}ULL;
    b.memSize = b.memSizeActual = {end - base}ULL;
    b.topOfKernelData = {max(v[1] for v in alloc.values())}ULL;
    b.deviceTreeP = (void *)(uintptr_t){VIRT_BASE + alloc['adt'][0] - base}ULL;
    b.deviceTreeLength = {len(adt)};
    memcpy(b.CommandLine, "-v cpus=1", sizeof("-v cpus=1"));
    return fwrite(&b, 1, sizeof(b), stdout) == sizeof(b) ? 0 : 1;
}}
'''
with tempfile.TemporaryDirectory() as d:
    c, exe = Path(d) / 'abi.c', Path(d) / 'abi'
    c.write_text(source)
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    actual = subprocess.check_output([str(exe)])
    if actual != expected:
        raise SystemExit('FAIL: Python boot_args does not match Apple declarations')
print('Apple arm64 boot_args declarations: size/offsets and all 736 bytes match')
