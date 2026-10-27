#!/usr/bin/env python3
"""Import reviewed literal LineageOS configuration; never execute Android makefiles."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / 'common/devices/lemonades-boot.json'
PINS = json.loads(Path(__file__).with_name('sources.json').read_text())


def pinned_text(key, directory, filename):
    repo = ROOT / 'sources' / directory
    revision = PINS[key]['commit']
    head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if head != revision:
        raise ValueError(f'{directory}: expected {revision}, got {head}')
    return subprocess.check_output(['git', '-C', str(repo), 'show', f'{revision}:{filename}'], text=True)


def literal(text, key):
    matches = re.findall(r'^' + re.escape(key) + r'\s*:=\s*([^\n]+)', text, re.M)
    if len(matches) != 1 or any(c in matches[0] for c in '$\\'):
        raise ValueError(f'{key}: expected one literal assignment')
    return matches[0].split('#', 1)[0].strip()


def collect():
    common = pinned_text('device_common', 'device-sm8250-common', 'BoardConfigCommon.mk')
    device = pinned_text('device', 'device-lemonades', 'BoardConfig.mk')
    keys = ['BOARD_BOOT_HEADER_VERSION', 'BOARD_KERNEL_BASE', 'BOARD_KERNEL_PAGESIZE',
            'BOARD_BOOTIMAGE_PARTITION_SIZE', 'BOARD_INCLUDE_DTB_IN_BOOTIMG',
            'BOARD_KERNEL_SEPARATED_DTBO', 'BOARD_KERNEL_IMAGE_NAME', 'TARGET_KERNEL_CONFIG']
    for key in keys:
        if re.search(r'^' + key + r'\s*[:?+]?=', device, re.M):
            raise ValueError(f'device override needs review: {key}')
    values = {key: literal(common, key) for key in keys}
    if values['BOARD_INCLUDE_DTB_IN_BOOTIMG'] != 'true' or values['BOARD_KERNEL_SEPARATED_DTBO'] != 'true':
        raise ValueError('DTB layout changed; review before importing')
    boot = {
        'header_version': int(values['BOARD_BOOT_HEADER_VERSION'], 0),
        'base': int(values['BOARD_KERNEL_BASE'], 0),
        'pagesize': int(values['BOARD_KERNEL_PAGESIZE'], 0),
        'partition_size': int(values['BOARD_BOOTIMAGE_PARTITION_SIZE'], 0),
        'dtb_location': 'header_v2_dtb_section', 'separate_dtbo': True,
    }
    if (boot['header_version'], boot['pagesize']) != (2, 4096):
        raise ValueError('boot layout changed; review before importing')
    profile = {'schema_version': 1, 'target': 'lemonades',
               'sources': {key: PINS[key] for key in ('device', 'device_common')},
               'boot_image': boot}
    inventories = []
    for key, directory in [('device', 'device-lemonades'), ('device_common', 'device-sm8250-common')]:
        text = pinned_text(key, directory, 'proprietary-files.txt')
        # Keep relevant firmware entries with extraction directives intact, including source notes.
        entries = [line for line in text.splitlines() if re.match(
            r'-?(?:odm/firmware/(?:tp/20828/|tfa98xx\.cnt)|vendor/firmware/a650_)', line)]
        inventories.append({'source': key, 'upstream_origin_note': '\n'.join(text.splitlines()[:2]),
                            'selected_entries': entries, 'files_downloaded': False})
    return profile, {
        'profile': profile, 'android_kernel_config': values['TARGET_KERNEL_CONFIG'].split(),
        'android_kernel_image_name': values['BOARD_KERNEL_IMAGE_NAME'],
        'board_info': pinned_text('device', 'device-lemonades', 'board-info.txt').strip(),
        'firmware_inventory': inventories,
        'limits': ['Android boot layout is evidence, not proof a UEFI shim boots on this phone.',
                   'Android cmdline and Linux drivers are not directly usable as XNU drivers.',
                   'Shared blob origin is 8T; no firmware binaries or XBL supplied.'],
    }


def load_profile(path=PROFILE):
    profile = json.loads(path.read_text())
    if profile.get('schema_version') != 1 or profile.get('target') != 'lemonades':
        raise ValueError('invalid lemonades boot profile')
    if profile['sources'] != {key: PINS[key] for key in ('device', 'device_common')}:
        raise ValueError('boot profile source pins differ; regenerate and review')
    boot = profile['boot_image']
    if (boot['header_version'], boot['base'], boot['pagesize'], boot['dtb_location'],
            boot['separate_dtbo'], boot['partition_size']) != (2, 0, 4096, 'header_v2_dtb_section', True, 100663296):
        raise ValueError('unreviewed lemonades boot layout')
    return profile


def patch_mu_wrapper(source):
    """Pinned Mu omits pagesize and silently drops zero base; preserve both."""
    before = '        "header_version": "--header_version",'
    after = before + '\n        "pagesize":       "--pagesize",'
    condition = '        # Append Argument Value\n        if value:'
    if source.count(before) != 1 or source.count(condition) != 1:
        raise ValueError('Mu boot-image wrapper changed; review before patching')
    return source.replace(before, after).replace(condition,
        '        # Preserve valid zero values, especially boot base.\n        if value is not None:')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--write-profile', action='store_true', help='update the reviewed source profile')
    ap.add_argument('--output', type=Path, default=ROOT / 'out/lemonades/lineage-reference.json')
    args = ap.parse_args()
    profile, report = collect()
    if args.write_profile:
        PROFILE.write_text(json.dumps(profile, indent=2) + '\n')
    elif load_profile() != profile:
        ap.error('checked-in profile differs from pinned sources')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
