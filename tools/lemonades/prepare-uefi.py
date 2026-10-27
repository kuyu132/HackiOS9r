#!/usr/bin/env python3
"""Generate a candidate 9R Mu-Silicium overlay; never borrow another phone's blobs or DTB."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from lineage import load_profile, patch_mu_wrapper
import stock_memory

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mu', type=Path, default=ROOT / 'Mu-Silicium')
    ap.add_argument('--loader', type=Path, default=ROOT / 'out/lemonades/loader.efi')
    ap.add_argument('--output', type=Path, default=ROOT / 'out/lemonades/uefi-overlay')
    args = ap.parse_args()
    profile = load_profile()
    memory_profile = stock_memory.load()
    boot = profile['boot_image']
    mu, out = args.mu.resolve(), args.output.resolve()
    expected = json.loads(Path(__file__).with_name('sources.json').read_text())['mu']['commit']
    revision = subprocess.check_output(['git', '-C', str(mu), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != expected:
        ap.error(f'Mu-Silicium must be at {expected}; got {revision}')
    if out.exists():
        ap.error(f'output already exists: {out}; choose a fresh output directory')
    loader = args.loader.read_bytes()
    if b'LEMONADES PROBE: UEFI diagnostics only' not in loader:
        ap.error('expected the lemonades probe EFI, not the generic/prebuilt loader')
    base = 'Platforms/OnePlus/kebabPkg'
    files = subprocess.check_output(['git', '-C', str(mu), 'ls-tree', '-r', '--name-only', expected, base], text=True).splitlines()
    platform = out / 'Platforms/OnePlus/lemonadesPkg'
    for name in files:
        # Fetch pristine pinned text. Local changes to the donor must not silently enter this port.
        data = subprocess.check_output(['git', '-C', str(mu), 'show', f'{expected}:{name}'], text=True)
        data = data.replace('kebab', 'lemonades').replace('"8T"', '"9R"').replace('8T_lemonades', '9R_lemonades')
        path = out / name.replace('kebab', 'lemonades')
        if path.suffix == '.dsc':
            data = re.sub(r'SOC_TYPE\s*= 0', 'SOC_TYPE                       = 2', data)
            data = data.replace('B8DF34E2-F093-45ED-A3EF-F2BDC4128DAA', 'FCBCBBCA-411C-4B0D-8CFE-D239651A2D51')
            data = data.replace('  lemonades/AcpiTables.inf', '  # No 8T ACPI tables in the 9R probe.')
            data += ('\n[LibraryClasses]\n'
                     '  PlatformBootManagerLib|lemonadesPkg/Library/ProbeBootManagerLib/ProbeBootManagerLib.inf\n'
                     '  AcpiTableUpdateLib|SiliciumNullPkg/Library/AcpiTableUpdateLibNull/AcpiTableUpdateLibNull.inf\n')
        elif path.suffix == '.fdf':
            data = data.replace('  INF RuleOverride = ACPITABLE lemonades/AcpiTables.inf', '  # ACPI is not used by the probe.')
            marker = '  !include QcomPkg/Extra.fdf.inc'
            if data.count(marker) != 1:
                ap.error('donor FDF layout changed')
            data = data.replace(marker, '''  FILE APPLICATION = D87A6391-9637-493A-B640-3CB8AC573699 {
    SECTION PE32 = lemonadesPkg/Probe/loader.efi
    SECTION UI = "OnePlus 9R UEFI Probe"
  }
''' + marker)
        elif path.name == 'APRIORI.inc':
            # These donor entries are commented out in DXE.inc and therefore
            # absent from FVMAIN. Do not force-install them just to fill a list.
            for relative in ('TzDxe/TzDxeLA.inf', 'PILDxe/PILDxe.inf', 'GpiDxe/GpiDxe.inf'):
                line = '  INF Binaries/lemonades/QcomPkg/Drivers/' + relative + '\n'
                if data.count(line) != 1:
                    ap.error('unexpected donor APRIORI entry: ' + relative)
                data = data.replace(line, '')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    shutil.copytree(ROOT / 'uefi/lemonades/ProbeBootManagerLib', platform / 'Library/ProbeBootManagerLib')
    (platform / 'Library/MemoryMapLib/MemoryMapLib.c').write_text(stock_memory.source(memory_profile))
    (platform / 'Probe').mkdir()
    (platform / 'Probe/loader.efi').write_bytes(loader)
    config = subprocess.check_output(['git', '-C', str(mu), 'show', f'{expected}:Resources/Configs/kebab.toml'], text=True)
    if config.count('append_dtb         = true') != 1 or config.count('header_version = 1') != 1:
        ap.error('donor TOML layout changed')
    config = config.replace('append_dtb         = true', 'append_dtb         = false')
    config = config.replace('header_version = 1',
        f'header_version = {boot["header_version"]}\nbase = {boot["base"]}\npagesize = {boot["pagesize"]}\n'
        'dtb = "Resources/DTBs/lemonades.dtb"')
    (out / 'Resources/Configs').mkdir(parents=True)
    (out / 'Resources/Configs/lemonades.toml').write_text(config)
    wrapper = subprocess.check_output(['git', '-C', str(mu), 'show', f'{expected}:build_uefi.py'], text=True)
    (out / 'build_uefi.py').write_text(patch_mu_wrapper(wrapper))
    # Enumerate vendor inputs without synthesizing any of them.
    vendor = set()
    for path in platform.rglob('*.inc'):
        vendor.update(re.findall(r'Binaries/lemonades/[A-Za-z0-9_./-]+', path.read_text()))
    manifest = {'status': 'candidate; UEFI not compiled or boot-validated', 'mu_commit': expected,
                'donor': 'kebabPkg scaffolding; memory map replaced using reviewed 9R stock facts',
                'loader_sha256': hashlib.sha256(loader).hexdigest(),
                'lineage_boot_profile': profile,
                'stock_memory_profile': memory_profile,
                'wrapper_changes': ['pass pagesize', 'preserve zero-valued arguments such as base'],
                'missing_device_inputs': ['reviewed/patched 9R firmware drivers (stock extraction is available separately)',
                                         'hardware-selected Resources/DTBs/lemonades.dtb'],
                'vendor_references_including_optional': sorted(vendor)}
    (out / 'lemonades-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{out}\nGenerated 9R platform source; {len(vendor)} vendor paths inventoried. No stock DTB/blobs supplied.')


if __name__ == '__main__':
    main()
