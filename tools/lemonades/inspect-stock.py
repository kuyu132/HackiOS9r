#!/usr/bin/env python3
"""Split stock boot DTBs/DTBO entries and inventory ELF/UEFI evidence, offline only."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(b): return hashlib.sha256(b).hexdigest()


def fdt_size(b, offset=0):
    if offset + 40 > len(b):
        raise ValueError('truncated FDT')
    magic, size = struct.unpack_from('>II', b, offset)
    if magic != 0xd00dfeed or size < 40 or offset + size > len(b):
        raise ValueError('invalid FDT bounds')
    return size


def fdt_info(path):
    result = {'path': str(path), 'size': path.stat().st_size, 'sha256': sha(path.read_bytes())}
    for key, kind in [('model', 's'), ('compatible', 's'), ('qcom,msm-id', 'x'), ('qcom,board-id', 'x'),
                      ('qcom,pmic-id', 'x'), ('oplus,dtsi_no', 'x'), ('oplus,pcb_range', 'x')]:
        p = subprocess.run(['fdtget', '-t', kind, str(path), '/', key], capture_output=True, text=True)
        result[key] = (p.stdout.strip() if kind == 's' else [int(x, 16) for x in p.stdout.split()]) if p.returncode == 0 else None
    return result


def boot_parts(b):
    if len(b) < 1660 or b[:8] != b'ANDROID!':
        raise ValueError('not an Android boot image')
    page, version = struct.unpack_from('<II', b, 36)
    if version != 2 or page not in (2048, 4096, 8192, 16384):
        raise ValueError('only boot header v2 supported')
    sizes = {name: struct.unpack_from('<I', b, offset)[0] for name, offset in
             [('kernel', 8), ('ramdisk', 16), ('second', 24), ('recovery_dtbo', 1632), ('dtb', 1648)]}
    parts, offset = {}, page
    for name, size in sizes.items():
        if offset + size > len(b):
            raise ValueError('boot section outside image')
        parts[name] = {'offset': offset, 'size': size, 'sha256': sha(b[offset:offset + size])}
        offset += (size + page - 1) // page * page
    return {'version': version, 'pagesize': page, 'sections': parts,
            'kernel_addr': struct.unpack_from('<I', b, 12)[0],
            'ramdisk_addr': struct.unpack_from('<I', b, 20)[0],
            'tags_addr': struct.unpack_from('<I', b, 32)[0],
            'dtb_addr': struct.unpack_from('<Q', b, 1652)[0]}


def split_dtbo(b):
    if len(b) < 32:
        raise ValueError('short DTBO table')
    magic, total, header, entry_size, count, entries, page, version = struct.unpack_from('>8I', b)
    if (magic != 0xd7b7ab1e or total > len(b) or header != 32 or entry_size != 32 or version != 0
            or entries < header or entries + entry_size * count > total):
        raise ValueError('unsupported DTBO table')
    result = []
    for i in range(count):
        size, offset, ident, rev, *custom = struct.unpack_from('>8I', b, entries + i * entry_size)
        if offset < entries + entry_size * count or offset + size > total or fdt_size(b, offset) != size:
            raise ValueError('invalid DTBO entry')
        result.append({'index': i, 'offset': offset, 'size': size, 'id': ident, 'rev': rev, 'custom': custom})
    return result


def elf_segments(b):
    if len(b) < 64 or b[:6] != b'\x7fELF\x02\x01':
        raise ValueError('expected ELF64 little-endian')
    offset = struct.unpack_from('<Q', b, 32)[0]
    entry_size, count = struct.unpack_from('<HH', b, 54)
    if entry_size != 56 or offset + entry_size * count > len(b):
        raise ValueError('invalid ELF program table')
    segments = []
    for i in range(count):
        kind, flags, file_offset, va, pa, size, memory_size, align = struct.unpack_from('<IIQQQQQQ', b, offset + i * entry_size)
        if file_offset + size > len(b):
            raise ValueError('ELF segment outside image')
        segments.append({'index': i, 'type': kind, 'flags': flags, 'offset': file_offset,
                         'physical_address': pa, 'virtual_address': va, 'file_size': size,
                         'memory_size': memory_size, 'sha256': sha(b[file_offset:file_offset + size])})
    return segments


def inventory_uefi(dump, output):
    files = []
    for info in sorted(dump.rglob('info.txt')):
        text = info.read_text()
        if not text.startswith('Type: File\n'):
            continue
        guid = re.search(r'^File GUID: ([A-F0-9-]{36})$', text, re.M)
        if not guid:
            continue
        name = re.search(r'^Text: (.+)$', text, re.M)
        name = name[1] if name else guid[1]
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', name)
        folder = output / (safe + '_' + guid[1])
        subtype = re.search(r'^Subtype: (.+)$', text, re.M)
        record = {'name': name, 'guid': guid[1], 'file_type': subtype[1] if subtype else None, 'sections': []}
        for section in sorted(info.parent.glob('*/info.txt')):
            details = section.read_text()
            sub = re.search(r'^Subtype: (.+)$', details, re.M)
            if not sub or sub[1] not in ('PE32 image', 'TE image', 'Raw', 'DXE dependency'):
                continue
            source = section.parent / 'body.bin'
            if not source.is_file():
                continue
            kind = {'PE32 image': 'pe32', 'TE image': 'te', 'Raw': 'raw', 'DXE dependency': 'depex'}[sub[1]]
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / f'{kind}.bin'
            if any(s['kind'] == kind for s in record['sections']):
                raise ValueError('ambiguous duplicate UEFI section: ' + str(info))
            data = source.read_bytes()
            dest.write_bytes(data)
            record['sections'].append({'kind': kind, 'path': str(dest), 'size': len(data), 'sha256': sha(data)})
        files.append(record)
    return files


def memory_rows(config):
    section, rows = '', []
    for line in config.splitlines():
        if line.startswith('['):
            section = line.strip('[]')
        if section in ('MemoryMap', 'RegisterMap') and line.strip().startswith('0x'):
            fields = next(csv.reader([line], skipinitialspace=True))
            if len(fields) != 8:
                raise ValueError('unexpected memory config row')
            rows.append({'name': fields[2].strip(), 'address': int(fields[0], 0), 'size': int(fields[1], 0),
                         'attributes': [v.strip() for v in fields[3:]], 'section': section})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stock', type=Path)
    args = ap.parse_args()
    stock = args.stock.resolve()
    extraction = json.loads((stock / 'extraction.json').read_text())
    # Do not analyze silently modified or partial partition images.
    for item in extraction['extracted']:
        if sha((stock / (item['name'] + '.img')).read_bytes()) != item['sha256']:
            raise ValueError('partition changed since extraction: ' + item['name'])
    out = stock / 'analysis'
    out.mkdir(exist_ok=True)
    report = {'boot': {}, 'dtbo': [], 'xbl': {}, 'stock': str(stock)}
    for name in ['boot', 'recovery']:
        binary = (stock / f'{name}.img').read_bytes()
        layout = boot_parts(binary)
        part = layout['sections']['dtb']
        data = binary[part['offset']:part['offset'] + part['size']]
        offset, trees = 0, []
        folder = out / name
        folder.mkdir(exist_ok=True)
        while offset < len(data):
            size = fdt_size(data, offset)
            dest = folder / f'dtb-{len(trees):02d}.dtb'
            dest.write_bytes(data[offset:offset + size])
            trees.append(fdt_info(dest) | {'offset_in_dtb_section': offset})
            offset += size
        layout['trees'] = trees
        report['boot'][name] = layout
    dtbo = (stock / 'dtbo.img').read_bytes()
    folder = out / 'dtbo'
    folder.mkdir(exist_ok=True)
    for entry in split_dtbo(dtbo):
        dest = folder / f'overlay-{entry["index"]:02d}.dtbo'
        dest.write_bytes(dtbo[entry['offset']:entry['offset'] + entry['size']])
        report['dtbo'].append(entry | fdt_info(dest))
    for name in ['xbl', 'xbl_lp5']:
        binary = (stock / f'{name}.img').read_bytes()
        segments = elf_segments(binary)
        modules = inventory_uefi(stock / f'{name}.img.dump', out / name / 'modules')
        config = [s for m in modules if m['name'] == 'uefiplat.cfg' for s in m['sections'] if s['kind'] == 'raw']
        if len(config) != 1:
            raise ValueError(f'{name}: unique uefiplat.cfg missing; run UEFIExtract all first')
        cfg = Path(config[0]['path']).read_text().rstrip('\0')
        (out / name / 'uefiplat.cfg').write_text(cfg)
        report['xbl'][name] = {'sha256': sha(binary), 'segments': segments, 'modules': modules,
                               'memory_map': memory_rows(cfg), 'uefiplat_sha256': config[0]['sha256']}
    (out / 'inventory.json').write_text(json.dumps(report, indent=2) + '\n')
    print(out / 'inventory.json')
    print('boot trees:', len(report['boot']['boot']['trees']), 'DTBO entries:', len(report['dtbo']))
    for name, item in report['xbl'].items():
        print(name, len(item['modules']), 'UEFI files;', len(item['memory_map']), 'memory/register regions')


if __name__ == '__main__':
    main()
