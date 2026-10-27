#!/usr/bin/env python3
"""Offline ADT/arm64 boot_args contract fixtures; never a device boot payload."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
U64 = 1 << 64
PAGE = 0x4000
VIRT_BASE = 0xFFFFFFF004000000


def number(value):
    if isinstance(value, bool):
        raise ValueError('boolean is not an address')
    if isinstance(value, str):
        return int(value, 0)
    if not isinstance(value, int):
        raise ValueError('integer required')
    return value


def interval(row):
    start, size = number(row['address']), number(row['size'])
    if start < 0 or size <= 0 or start + size > U64:
        raise ValueError('invalid or wrapping interval')
    return start, start + size


def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def validate_layout(plan, stock):
    if plan['target'] != 'lemonades' or plan.get('purpose') != 'offline-contract-fixture':
        raise ValueError('only explicit lemonades offline fixtures supported')
    if number(plan['page_size']) != PAGE or plan['command_line'] != '-v cpus=1':
        raise ValueError('first contract is 16K, single core, no peripheral options')
    if number(plan['mpidr']) not in range(0, 0x800, 0x100):
        raise ValueError('MPIDR outside DT-derived candidate topology')
    if not 0 < number(plan['cntfrq']) < 1 << 32:
        raise ValueError('invalid counter frequency')
    bank = interval(plan['ram_window'])
    if any(x % PAGE for x in bank) or VIRT_BASE + bank[1] - bank[0] >= U64:
        raise ValueError('unaligned or overflowing RAM window')
    reserved = [interval(r) for r in stock['stock_regions'] if r['section'] == 'MemoryMap']
    reserved += [(0x80000000, 0x80600000)]
    # A single XNU window cannot silently include holes even if allocations miss them.
    if any(overlaps(bank, r) for r in reserved):
        raise ValueError('RAM window overlaps stock firmware/runtime reservations')
    rows = plan['allocations']
    required = {'kernel', 'ramdisk', 'adt', 'boot_args', 'stack'}
    if len(rows) != len(required) or {r['name'] for r in rows} != required:
        raise ValueError('missing, duplicate or unknown allocation')
    used = []
    for row in rows:
        bounds = interval(row)
        if any(v % PAGE for v in bounds):
            raise ValueError('allocations must be 16K aligned')
        if not (bank[0] <= bounds[0] < bounds[1] <= bank[1]):
            raise ValueError('allocation outside RAM window')
        if any(overlaps(bounds, other) for other in used):
            raise ValueError('allocation overlap')
        used.append(bounds)
    return {r['name']: interval(r) for r in rows}


def cstr(s):
    return s.encode('ascii') + b'\0'


def node(name, props=None, children=()):
    props = {'name': cstr(name), **(props or {})}
    data = struct.pack('<II', len(props), len(children))
    for key, value in props.items():
        key = cstr(key)
        if len(key) > 32:
            raise ValueError('ADT property name too long')
        data += key.ljust(32, b'\0') + struct.pack('<I', len(value)) + value + b'\0' * (-len(value) % 4)
    return data + b''.join(children)


def parse_adt(data):
    """Bounded independent decoder: no duplicate keys/children, trailing data or truncation."""
    def read(offset, depth):
        if depth > 32 or offset + 8 > len(data):
            raise ValueError('invalid ADT node')
        nprops, nkids = struct.unpack_from('<II', data, offset)
        offset += 8
        if nprops > 256 or nkids > 256:
            raise ValueError('excessive ADT counts')
        props, kids = {}, {}
        for _ in range(nprops):
            if offset + 36 > len(data):
                raise ValueError('truncated ADT property')
            raw = data[offset:offset + 32]
            if b'\0' not in raw:
                raise ValueError('unterminated property name')
            name = raw.split(b'\0', 1)[0].decode('ascii')
            size, = struct.unpack_from('<I', data, offset + 32)
            offset += 36
            end = offset + ((size + 3) & ~3)
            if size & 0x80000000 or end > len(data) or name in props:
                raise ValueError('invalid ADT property length/duplicate')
            props[name] = data[offset:offset + size]
            offset = end
        if not props.get('name', b'').endswith(b'\0'):
            raise ValueError('missing ADT node name')
        for _ in range(nkids):
            child, offset = read(offset, depth + 1)
            name = child['properties']['name']
            if name in kids:
                raise ValueError('duplicate child')
            kids[name] = child
        return {'properties': props, 'children': kids}, offset
    tree, end = read(0, 0)
    if end != len(data):
        raise ValueError('trailing ADT bytes')
    return tree


def generate(plan, stock):
    alloc = validate_layout(plan, stock)
    base, end = interval(plan['ram_window'])
    u32 = lambda n: struct.pack('<I', n)
    u64 = lambda *n: struct.pack('<' + 'Q' * len(n), *n)
    chosen = node('chosen', {'hackios,board': cstr('lemonades'),
        'hackios,offline-only': u32(1), 'psci-method': cstr('smc'),
        'dram-base': u64(base), 'dram-size': u64(end - base)}, [
        node('memory-map', {'RAMDisk': u64(alloc['ramdisk'][0], alloc['ramdisk'][1] - alloc['ramdisk'][0])})])
    cpu = node('cpu0', {'device_type': cstr('cpu'), 'state': cstr('running'),
        'reg': u32(number(plan['mpidr'])), 'cpu-id': u32(0),
        'timebase-frequency': u64(number(plan['cntfrq'])),
        'fixed-frequency': u64(number(plan['cntfrq']))})
    gic = node('gic', {'device_type': cstr('interrupt-controller'), 'compatible': cstr('arm,gic-v3'),
        'reg': u64(0x17A00000 - 0x400000, 0x10000, 0x17A60000 - 0x400000, 0x100000)})
    adt = node('device-tree', {'model': cstr('lemonades-offline-contract')}, [chosen,
        node('cpus', children=[cpu]), node('arm-io', {'device_type': cstr('lemonades'),
        'ranges': u64(0, 0x400000, 0x3FC00000), '#address-cells': u32(2), '#size-cells': u32(2)}, [gic])])
    parse_adt(adt)
    if len(adt) > alloc['adt'][1] - alloc['adt'][0]:
        raise ValueError('ADT does not fit allocation')
    # Apple xnu-8796.121.2 arm64 boot_args ABI: padding is explicit, video stays disabled.
    args = bytearray(736)
    struct.pack_into('<HH', args, 0, 2, 2)
    struct.pack_into('<QQQQ', args, 8, VIRT_BASE, base, end - base, max(v[1] for v in alloc.values()))
    struct.pack_into('<QI', args, 96, VIRT_BASE + alloc['adt'][0] - base, len(adt))
    cmd = cstr(plan['command_line'])
    args[108:108 + len(cmd)] = cmd
    struct.pack_into('<QQ', args, 720, 0, end - base)
    return adt, bytes(args)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--plan', type=Path, default=ROOT / 'common/lemonades/boot-contract-fixture.json')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    plan = json.loads(args.plan.read_text())
    stock_path = ROOT / 'uefi/lemonades/stock-memory.json'
    adt, ba = generate(plan, json.loads(stock_path.read_text()))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'hardware.adt').write_bytes(adt)
    (args.output / 'boot-args.bin').write_bytes(ba)
    report = {'bootable': False, 'scope': 'synthetic memory/counter fixture; no measured free RAM, kernel segments, user-space identity or handoff',
        'plan': plan, 'stock_sha256': hashlib.sha256(stock_path.read_bytes()).hexdigest(),
        'adt_sha256': hashlib.sha256(adt).hexdigest(), 'boot_args_sha256': hashlib.sha256(ba).hexdigest()}
    (args.output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print('ADT + arm64 boot_args validation fixture generated; NOT BOOTABLE')


if __name__ == '__main__':
    main()
