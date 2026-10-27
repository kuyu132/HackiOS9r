#!/usr/bin/env python3
"""Offline DXE dependency/APRIORI audit. GUID occurrences are NOT providers."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import uuid

ROOT = Path(__file__).resolve().parents[2]
APRIORI = 'FC510EE7-FFDC-11D4-BD41-0080C73C8881'
PROBE = 'D87A6391-9637-493A-B640-3CB8AC573699'


def guid(data):
    return str(uuid.UUID(bytes_le=data)).upper()


def depex(data):
    """Validate PI DXE bytecode, retaining expression semantics and dispatch mode.

    Missing DEPEX is different from TRUE. BEFORE/AFTER reference firmware FILE
    GUIDs, not protocol GUIDs. SOR requires an explicit scheduling request.
    """
    if data is None:
        return {'mode': 'all_architectural_protocols', 'protocols': [], 'expression': None}
    if not data:
        raise ValueError('empty DEPEX section')
    if data[0] in (0, 1):
        if len(data) != 18 or data[-1] != 8:
            raise ValueError('malformed BEFORE/AFTER')
        return {'mode': ('before', 'after')[data[0]], 'file_guid': guid(data[1:17]), 'protocols': [], 'expression': None}
    stack, protocols, pos, sor = [], set(), 0, False
    while pos < len(data):
        opcode = data[pos]
        pos += 1
        if opcode == 2:
            if pos + 16 > len(data):
                raise ValueError('truncated GUID')
            value = guid(data[pos:pos + 16]); pos += 16
            protocols.add(value); stack.append(value)
        elif opcode in (3, 4):
            if len(stack) < 2:
                raise ValueError('DEPEX stack underflow')
            right, left = stack.pop(), stack.pop()
            stack.append({'and' if opcode == 3 else 'or': [left, right]})
        elif opcode == 5:
            if not stack:
                raise ValueError('DEPEX stack underflow')
            stack.append({'not': stack.pop()})
        elif opcode in (6, 7):
            stack.append(opcode == 6)
        elif opcode == 9 and pos == 1:
            sor = True
        elif opcode == 8:
            if pos != len(data) or len(stack) != 1:
                raise ValueError('invalid DEPEX END or trailing bytes')
            return {'mode': 'schedule_on_request' if sor else 'expression',
                    'protocols': sorted(protocols), 'expression': stack[0]}
        else:
            raise ValueError(f'unsupported/misplaced DEPEX opcode {opcode:#x}')
    raise ValueError('missing DEPEX END')


def read_section(module, kind):
    sections = [s for s in module['sections'] if s['kind'] == kind]
    if not sections:
        return None
    if len(sections) != 1:
        raise ValueError('duplicate section kind')
    s = sections[0]; data = Path(s['path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != s['sha256']:
        raise ValueError('section hash changed: ' + s['path'])
    return data


def apriori(modules):
    files = [m for m in modules if m['guid'] == APRIORI]
    if len(files) != 1:
        raise ValueError('expected one APRIORI file')
    data = read_section(files[0], 'raw')
    if data is None or len(data) % 16:
        raise ValueError('invalid APRIORI GUID array')
    result = [guid(data[i:i + 16]) for i in range(0, len(data), 16)]
    if len(set(result)) != len(result):
        raise ValueError('duplicate APRIORI GUID')
    return result


def guid_names(build):
    names = {}
    for base in ('Mu_Basecore', 'Common', 'Silicon'):
        for path in sorted((build / base).rglob('*.dec')):
            for match in re.finditer(r'(\w+)\s*=\s*\{\s*(0x[\da-fA-F]+)\s*,\s*(0x[\da-fA-F]+)\s*,\s*(0x[\da-fA-F]+)\s*,\s*\{([^}]+)\}\s*\}', path.read_text(errors='replace')):
                tail = re.findall(r'0x[\da-fA-F]+', match[5])
                if len(tail) != 8:
                    continue
                key = guid(struct.pack('<IHH8B', *(int(match[i], 16) for i in (2, 3, 4)), *(int(x, 16) for x in tail)))
                names.setdefault(key, []).append({'name': match[1], 'source': str(path.relative_to(build))})
    return names


def analyze(modules, stock, names):
    by = {m['guid']: m for m in modules}
    stock_by = {m['guid']: m for m in stock}
    order, stock_order = apriori(modules), apriori(stock)
    binary = {m['guid']: read_section(m, 'pe32') for m in modules}
    stock_binary = {m['guid']: read_section(m, 'pe32') for m in stock}
    rows, references = [], set()
    for m in modules:
        if binary[m['guid']] is None:
            continue
        if m.get('file_type') in ('Application', 'DXE core', 'SEC core', 'PEI core', 'PEI module'):
            continue  # Applications/cores do not use DXE driver scheduling rules.
        dependency = depex(read_section(m, 'depex'))
        references.update(dependency['protocols'])
        rows.append({'guid': m['guid'], 'name': m['name'], 'dependency': dependency,
                     'apriori_index': order.index(m['guid']) if m['guid'] in order else None,
                     'stock_apriori_index': stock_order.index(m['guid']) if m['guid'] in stock_order else None,
                     'depex_bypassed': m['guid'] in order})
    guids = []
    for g in sorted(references):
        needle = uuid.UUID(g).bytes_le
        current = [{'guid': k, 'name': by[k]['name']} for k, b in binary.items() if k != PROBE and b is not None and needle in b]
        omitted = [{'guid': k, 'name': stock_by[k]['name']} for k, b in stock_binary.items() if k not in by and b is not None and needle in b]
        guids.append({'guid': g, 'names': names.get(g, []), 'current_pe_occurrences': current,
                      'omitted_stock_pe_occurrences': omitted,
                      'provider_status': 'UNRESOLVED: byte occurrence does not prove protocol installation'})
    return {'apriori_count': len(order), 'stock_apriori_count': len(stock_order),
            'dangling_apriori': [{'index': i, 'guid': g, 'stock_name': stock_by.get(g, {}).get('name')}
                                 for i, g in enumerate(order) if g not in by],
            'drivers': rows, 'protocols': guids,
            'limits': ['APRIORI dispatch bypasses DEPEX; it does not assert successful entry points.',
                       'PE GUID occurrence may be a consumer, producer, data or dead code; NOT a dependency closure proof.',
                       'Diagnostic application watch-list bytes are excluded from PE occurrence counts.',
                       'No protocol installation, hardware initialization or phone boot has been executed.',
                       'Absent PE bytes do not rule out constructed GUIDs, boot-service providers or later firmware volumes.']}


def watch_header(report):
    lines = ['/* Generated from protocol_audit.py; read-only LocateProtocol diagnostics. */',
             '#ifndef LEMONADES_PROTOCOL_WATCH_H', '#define LEMONADES_PROTOCOL_WATCH_H',
             'static const struct { const char *name; efi_guid guid; } lemonades_protocol_watch[] = {']
    for item in report['protocols']:
        g = uuid.UUID(item['guid'])
        name = item['names'][0]['name'] if item['names'] else item['guid']
        tail = ', '.join(f'0x{b:02x}' for b in g.bytes[8:])
        lines.append(f'  {{"{name}", {{0x{g.time_low:08x}, 0x{g.time_mid:04x}, 0x{g.time_hi_version:04x}, {{{tail}}}}}}},')
    return '\n'.join(lines + ['};', '#endif', ''])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('artifact', type=Path)
    ap.add_argument('--build-tree', type=Path, required=True)
    ap.add_argument('--stock', type=Path, default=ROOT / 'out/lemonades/stock/LE2101_14.0.0.2301')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--watch-header', type=Path)
    args = ap.parse_args()
    verified = json.loads((args.artifact / 'verification.json').read_text())
    if hashlib.sha256(Path(verified['fd']).read_bytes()).hexdigest() != verified['fd_sha256']:
        raise ValueError('artifact changed since verification')
    stock = json.loads((args.stock / 'analysis/inventory.json').read_text())['xbl'][verified['variant']]
    if stock['sha256'] != verified['xbl_sha256']:
        raise ValueError('mismatched stock variant')
    result = analyze(json.loads((args.artifact / 'inventory.json').read_text()), stock['modules'], guid_names(args.build_tree))
    result.update({'variant': verified['variant'], 'fd_sha256': verified['fd_sha256']})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if args.watch_header:
        args.watch_header.write_text(watch_header(result))
    print(f"{len(result['drivers'])} PE driver files; {len(result['protocols'])} DEPEX GUIDs; {len(result['dangling_apriori'])} dangling APRIORI entries")


if __name__ == '__main__':
    main()
