#!/usr/bin/env python3
"""Re-extract a built probe FD and verify its contents; never access a device."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import uuid
from protocol_audit import apriori

ROOT = Path(__file__).resolve().parents[2]
PROBE_GUID = 'D87A6391-9637-493A-B640-3CB8AC573699'
BDS_GUID = '6D33944A-EC75-4855-A54D-809C75241F6C'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_header(data):
    if len(data) != 0x300000 or data[40:44] != b'_FVH':
        raise ValueError('expected a 3 MiB firmware volume')
    length = struct.unpack_from('<Q', data, 32)[0]
    header = struct.unpack_from('<H', data, 48)[0]
    if length != len(data) or header < 56 or header > length or header % 2:
        raise ValueError('invalid FV header bounds')
    if sum(struct.unpack_from('<' + 'H' * (header // 2), data)) & 0xffff:
        raise ValueError('FV header checksum mismatch')


def check_sections(modules, staging, expected_probe):
    by_guid = {}
    for module in modules:
        guid = module['guid']
        if guid in by_guid:
            raise ValueError('duplicate firmware file GUID: ' + guid)
        by_guid[guid] = module
    probe = by_guid.get(PROBE_GUID, {})
    sections = probe.get('sections', [])
    if len(sections) != 1 or sections[0]['kind'] != 'pe32' or sections[0]['sha256'] != expected_probe:
        raise ValueError('embedded probe does not match the build input')
    included, excluded = [], []
    for item in staging['staged']:
        module = by_guid.get(item['guid'].upper())
        if module is None:
            excluded.append({'name': item['stock_name'], 'guid': item['guid'], 'path': item['path']})
            continue
        expected = [f['sha256'] for f in item.get('files', [])] or [item['sha256']]
        actual = [s['sha256'] for s in module['sections']]
        if sorted(expected) != sorted(actual):
            raise ValueError('stock section changed: ' + item['stock_name'])
        included.append({'name': item['stock_name'], 'guid': item['guid'],
                         'sections': [{k: s[k] for k in ('kind', 'size', 'sha256')} for s in module['sections']]})
    return included, excluded


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('build_tree', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--extractor', type=Path, default=ROOT / 'out/lemonades/uefiextract-build/UEFIExtract')
    args = ap.parse_args()
    build, out = args.build_tree.resolve(), args.output.resolve()
    if out.exists():
        ap.error('output exists; use a fresh directory to avoid stale extraction results')
    fv = build / 'Build/lemonadesPkg/RELEASE_CLANGPDB/FV'
    fd = fv / 'SILICIUM_UEFI.fd'
    binary = fd.read_bytes()
    check_header(binary)
    execution = json.loads((build / 'build-execution.json').read_text())
    if execution['fd_sha256'] != sha(binary):
        raise ValueError('FD differs from the completed build record')
    inputs = json.loads((build / 'build-inputs.json').read_text())
    for relative, expected in inputs['overlay_files_sha256'].items():
        if sha((build / relative).read_bytes()) != expected:
            raise ValueError('overlay input changed after preparation: ' + relative)
    staging = json.loads((build / 'stock-staging.json').read_text())
    manifest = json.loads((build / 'lemonades-manifest.json').read_text())
    loader = build / 'Platforms/OnePlus/lemonadesPkg/Probe/loader.efi'
    if sha(loader.read_bytes()) != manifest['loader_sha256']:
        raise ValueError('probe input differs from overlay manifest')
    report_path = build / 'Build/lemonades-report.txt'
    report = report_path.read_text()
    if '/ProbeBootManagerLib/ProbeBootManagerLib.inf' not in report or 'KernelErrataPatcherLib' in report:
        raise ValueError('probe boot manager missing, or Windows memory hooks linked')
    out.mkdir(parents=True)
    extracted_fd = out / 'lemonades-probe.fd'
    shutil.copyfile(fd, extracted_fd)
    run = subprocess.run([str(args.extractor.resolve()), str(extracted_fd), 'all'], capture_output=True, text=True)
    (out / 'extractor.log').write_text(run.stdout + run.stderr)
    run.check_returncode()
    spec = importlib.util.spec_from_file_location('inspect_stock', Path(__file__).with_name('inspect-stock.py'))
    inspect_stock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inspect_stock)
    modules = inspect_stock.inventory_uefi(Path(str(extracted_fd) + '.dump'), out / 'modules')
    by_guid = {m['guid']: m for m in modules}
    dangling = set(apriori(modules)) - by_guid.keys()
    if dangling:
        raise ValueError('APRIORI references absent firmware files: ' + ', '.join(sorted(dangling)))
    # Compare the actual FD against the build tool's resolved list, including
    # conditional branches. Staged but disabled display XML is not required.
    expected_guids = set()
    for name in ('FVMAIN', 'FVMAIN_COMPACT'):
        for match in re.finditer(r'^EFI_FILE_NAME\s*=\s*(.+)$', (fv / (name + '.inf')).read_text(), re.M):
            ffs = Path(match[1].strip()).read_bytes()
            expected_guids.add(str(uuid.UUID(bytes_le=ffs[:16])).upper())
    missing = expected_guids - by_guid.keys()
    if missing:
        raise ValueError('built FFS missing from FD: ' + ', '.join(sorted(missing)))
    included, excluded = check_sections(modules, staging, manifest['loader_sha256'])
    bds_sections = by_guid.get(BDS_GUID, {}).get('sections', [])
    bds_pe = [s for s in bds_sections if s['kind'] == 'pe32']
    if len(bds_pe) != 1 or 'OnePlus 9R: experimental UEFI probe'.encode('utf-16-le') not in Path(bds_pe[0]['path']).read_bytes():
        raise ValueError('BDS does not contain the probe boot manager banner')
    for module in modules:
        for section in module['sections']:
            if section['kind'] != 'pe32':
                continue
            pe = Path(section['path']).read_bytes()
            offset = struct.unpack_from('<I', pe, 60)[0] if pe[:2] == b'MZ' else 0
            if pe[offset:offset + 4] != b'PE\0\0' or struct.unpack_from('<H', pe, offset + 4)[0] != 0xaa64:
                raise ValueError('non-AArch64 PE: ' + module['name'])
    result = {'status': 'offline build and content verification passed; NOT boot-validated',
              'variant': staging['variant'], 'xbl_sha256': staging['xbl_sha256'],
              'fd': str(extracted_fd), 'fd_size': len(binary), 'fd_sha256': sha(binary),
              'loader_sha256': manifest['loader_sha256'], 'build_report_sha256': sha(report_path.read_bytes()),
              'build_inputs': inputs,
              'build_execution': execution,
              'resolved_ffs_count': len(expected_guids), 'extracted_file_count': len(modules),
              'included_stock': included, 'excluded_staged_stock': excluded,
              'selected_dtb': None, 'hardware_boot_tested': False,
              'limits': ['UEFIExtract volume-top warning is retained in extractor.log; this is an ARM FV.',
                         'Static inclusion and DEPEX byte preservation do not prove protocol availability.',
                         'Stock driver initialization and memory reservations still need review and hardware tests.']}
    (out / 'inventory.json').write_text(json.dumps(modules, indent=2) + '\n')
    (out / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('variant', 'fd_size', 'fd_sha256', 'resolved_ffs_count')}, indent=2))
    print(f'{len(included)} stock files unchanged; {len(excluded)} staged files excluded by build configuration')


if __name__ == '__main__':
    main()
