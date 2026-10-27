#!/usr/bin/env python3
"""Stage unmodified 9R UEFI sections by GUID and all matching SoC DTB candidates.

Only INF text is reused from Mu's pinned 8T binary package. Every staged binary
comes from the selected 9R XBL. Does not patch drivers or choose a phone's DTB.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_COMMIT = 'a1501e0c2e642d6ac0d8f52c85af2a67b75a7799'


def verified(item):
    data = Path(item['path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != item['sha256']:
        raise ValueError('modified extracted section: ' + item['path'])
    if item.get('kind') == 'pe32':
        offset = struct.unpack_from('<I', data, 60)[0] if len(data) >= 64 and data[:2] == b'MZ' else 0
        if (offset + 6 > len(data) or data[offset:offset + 4] != b'PE\0\0' or
                struct.unpack_from('<H', data, offset + 4)[0] != 0xaa64):
            raise ValueError('expected AArch64 PE driver: ' + item['path'])
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stock', type=Path)
    ap.add_argument('overlay', type=Path)
    ap.add_argument('--variant', choices=['xbl', 'xbl_lp5'], required=True)
    args = ap.parse_args()
    stock, overlay = args.stock.resolve(), args.overlay.resolve()
    data = json.loads((stock / 'analysis/inventory.json').read_text())
    manifest_path = overlay / 'lemonades-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if (overlay / 'Binaries/lemonades').exists():
        ap.error('stock binaries already staged; use a fresh overlay')
    expected_hash = manifest['stock_memory_profile'][args.variant + '_sha256']
    actual_hash = hashlib.sha256((stock / (args.variant + '.img')).read_bytes()).hexdigest()
    if data['xbl'][args.variant]['sha256'] != actual_hash or actual_hash != expected_hash:
        ap.error('stock XBL differs from reviewed memory profile')
    modules = {m['guid']: m for m in data['xbl'][args.variant]['modules']}
    refs = manifest['vendor_references_including_optional']
    staged, missing = [], []
    templates = ROOT / 'sources/device-binaries-templates'
    for ref in refs:
        dest = overlay / ref
        if dest.suffix != '.inf':
            continue
        template_path = ref.replace('Binaries/lemonades/', 'kebab/', 1)
        template = subprocess.check_output(['git', '-C', str(templates), 'show',
                                           TEMPLATE_COMMIT + ':' + template_path], text=True)
        guid = re.search(r'FILE_GUID\s*=\s*([A-Fa-f0-9-]{36})', template)[1].upper()
        module = modules.get(guid)
        if not module:
            missing.append({'path': ref, 'reason': 'GUID absent in stock XBL', 'guid': guid})
            continue
        sections = {s['kind']: s for s in module['sections']}
        requested = re.findall(r'^\s*(PE32|TE|DXE_DEPEX)\|([^|\s]+)\|', template, re.M)
        mapping = {'PE32': 'pe32', 'TE': 'te', 'DXE_DEPEX': 'depex'}
        if not requested or any(mapping[kind] not in sections for kind, _ in requested):
            missing.append({'path': ref, 'reason': 'required stock section absent', 'guid': guid})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        copied = []
        for kind, filename in requested:
            if Path(filename).name != filename:
                raise ValueError('unexpected binary path in INF')
            section = sections[mapping[kind]]
            (dest.parent / filename).write_bytes(verified(section))
            copied.append({'file': filename, 'sha256': section['sha256'], 'source_section': section['path']})
        dest.write_text(template)
        staged.append({'path': ref, 'guid': guid, 'stock_name': module['name'], 'files': copied})
    raw = (overlay / 'Platforms/OnePlus/lemonadesPkg/Include/RAW.inc').read_text()
    for guid, body in re.findall(r'FILE FREEFORM\s*=\s*([A-Fa-f0-9-]{36})\s*\{([^}]+)\}', raw):
        ref = re.search(r'SECTION RAW\s*=\s*(\S+)', body)[1]
        module = modules.get(guid.upper())
        candidates = [s for s in module['sections'] if s['kind'] == 'raw'] if module else []
        if len(candidates) != 1:
            missing.append({'path': ref, 'guid': guid, 'reason': 'unique raw section absent in stock XBL'})
            continue
        dest = overlay / ref
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(verified(candidates[0]))
        staged.append({'path': ref, 'guid': guid, 'stock_name': module['name'],
                       'sha256': candidates[0]['sha256'], 'source_section': candidates[0]['path']})
    candidates_dir = overlay / 'Resources/DTBs/candidates'
    candidates_dir.mkdir(parents=True, exist_ok=True)
    overlays = [d for d in data['dtbo'] if d['oplus,dtsi_no'] == [20828] and d['qcom,board-id'] == [0x10008, 0]]
    if len(overlays) != 1:
        raise ValueError('ambiguous/missing 9R DTBO selection')
    dtbo = overlays[0]
    verified(dtbo)
    dtbs = []
    for base in data['boot']['boot']['trees']:
        if base['oplus,dtsi_no'] != [20828]:
            continue
        verified(base)
        msm = base['qcom,msm-id']
        if len(msm) != 2 or msm[0] != 356:
            raise ValueError('unexpected 9R SoC ID')
        dest = candidates_dir / f'lemonades-{msm[1]:08x}.dtb'
        subprocess.run(['fdtoverlay', '-i', base['path'], '-o', str(dest), dtbo['path']], check=True)
        subprocess.run([sys.executable, str(ROOT / 'tools/lemonades/inspect-dtb.py'), str(dest),
                        '--output', str(dest.with_suffix('.json'))], check=True)
        dtbs.append({'path': str(dest), 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(),
                     'msm_id': msm, 'base_sha256': base['sha256'], 'overlay_sha256': dtbo['sha256']})
    if len(dtbs) != 3:
        raise ValueError('expected all three 9R SoC revision candidates')
    report = {'status': 'staged stock binaries, UNPATCHED and NOT boot-validated',
              'stock': str(stock), 'variant': args.variant, 'xbl_sha256': actual_hash,
              'inf_template_commit': TEMPLATE_COMMIT, 'staged': staged, 'missing': missing,
              'dtb_candidates': dtbs, 'selected_dtb': None,
              'limits': ['No donor binaries copied; matched by firmware file GUID, not UI name.',
                         'Missing includes optional/commented template references; not an active build dependency count.',
                         'Vendor binary initialization, protocol dependencies and Mu-specific patches remain unreviewed.',
                         'No default lemonades.dtb is created without hardware SoC revision selection.']}
    (overlay / 'stock-staging.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest['stock_staging'] = {'variant': args.variant, 'xbl_sha256': actual_hash,
                                'staged_references': len(staged), 'missing_references': len(missing),
                                'binary_patches_applied': False, 'selected_dtb': None}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Staged {len(staged)} references; {len(missing)} missing (including optional); {len(dtbs)} DTB candidates.')


if __name__ == '__main__':
    main()
