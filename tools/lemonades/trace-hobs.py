#!/usr/bin/env python3
"""Map stock PE/TE GUID references without running firmware or inventing providers."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import uuid
import capstone as cs
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_REG
import pefile
from protocol_audit import read_section

HOBS = {
    'InfoBlk': '90A49AFD-422F-08AE-9611-E788D3804845',
    'Shim': 'BEDAEABC-5E70-4D66-9733-213D072B9D04',
    'Scheduler': '8EC2BD8D-56D7-49EF-8796-631778F8EBF8',
    'FvList': '12DBD93D-402A-416E-EC20-5F80CF5F7FE7',
    'DtbExtension': '3A06E1E8-61F6-11EB-BBED-4B476E2FF6A7',
    'KernelProtocol': 'B5062BE7-170B-4A32-BE21-689262FF4399',
}
UNRESOLVED = ['0F9B9E33-B8E4-4E6D-A83E-2B6710A1CC24', '47861DFF-556F-4269-9B28-062EC3ECB30D',
              'A966CC4F-EE6C-424D-A762-8ED3B5A4A501', '76B95DAD-1E66-4D98-9CE7-B294D9596895']


def sections(data, kind):
    """Return initialized section bytes at preferred virtual addresses (not live addresses)."""
    result = []
    if kind == 'pe32':
        pe = pefile.PE(data=data)
        if pe.FILE_HEADER.Machine != 0xaa64:
            raise ValueError('expected AArch64 PE')
        base = pe.OPTIONAL_HEADER.ImageBase
        entries = [(s.Name, s.VirtualAddress, s.SizeOfRawData, s.PointerToRawData, s.Characteristics) for s in pe.sections]
    elif kind == 'te':
        if len(data) < 40:
            raise ValueError('short TE header')
        magic, machine, count, _, stripped, _, _, base = struct.unpack_from('<HHBBHIIQ', data)
        if magic != 0x5a56 or machine != 0xaa64 or stripped < 40 or count == 0 or 40 + count * 40 > len(data):
            raise ValueError('invalid TE header')
        delta = stripped - 40
        entries = []
        for i in range(count):
            name, _, rva, size, raw, _, _, _, _, flags = struct.unpack_from('<8sIIIIIIHHI', data, 40 + i * 40)
            entries.append((name, rva, size, raw - delta, flags))
    else:
        raise ValueError('unknown image kind')
    for name, rva, size, offset, flags in entries:
        if size == 0:
            continue
        if offset < 0 or offset + size > len(data) or base + rva + size > 1 << 64:
            raise ValueError('image section outside bounds')
        result.append({'name': name.rstrip(b'\0').decode('ascii'), 'address': base + rva,
                       'offset': offset, 'data': data[offset:offset + size], 'executable': bool(flags & 0x20000000)})
    return result


def references(image_sections, targets):
    decoder = cs.Cs(cs.CS_ARCH_ARM64, cs.CS_MODE_LITTLE_ENDIAN)
    decoder.detail = True
    decoder.skipdata = True
    result = []
    for section in image_sections:
        if not section['executable']:
            continue
        registers = {}
        for ins in decoder.disasm(section['data'], section['address']):
            if not ins.id:
                registers.clear(); continue
            operands = ins.operands; value = None
            if ins.mnemonic in ('adr', 'adrp') and len(operands) == 2 and operands[1].type == ARM64_OP_IMM:
                value = operands[1].imm
            elif ins.mnemonic == 'add' and len(operands) == 3 and operands[1].type == ARM64_OP_REG and operands[2].type == ARM64_OP_IMM:
                src = ins.reg_name(operands[1].reg)
                if src in registers:
                    value = registers[src] + (operands[2].imm << operands[2].shift.value)
            elif ins.mnemonic == 'mov' and len(operands) == 2 and operands[1].type == ARM64_OP_REG:
                value = registers.get(ins.reg_name(operands[1].reg))
            for reg in ins.regs_access()[1]:
                name = ins.reg_name(reg)
                registers.pop('x' + name[1:] if name.startswith('w') else name, None)
            if value is not None and operands and operands[0].type == ARM64_OP_REG:
                dest = ins.reg_name(operands[0].reg)
                if dest.startswith('x'):
                    registers[dest] = value
                    if value in targets:
                        result.append({'instruction_address': ins.address, 'bytes': ins.bytes.hex(),
                                       'instruction': ins.mnemonic + ' ' + ins.op_str,
                                       'target_address': value, 'target': targets[value]})
            if any(ins.group(group) for group in (cs.CS_GRP_JUMP, cs.CS_GRP_CALL, cs.CS_GRP_RET)):
                registers.clear()  # No speculative data flow across calls/branches.
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stock', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    inventory = json.loads((args.stock / 'analysis/inventory.json').read_text())
    result = {'scope': 'Static preferred addresses; no live pointers recovered or firmware executed', 'variants': {}}
    needles = {name: uuid.UUID(g).bytes_le for name, g in HOBS.items()}
    for variant in ('xbl', 'xbl_lp5'):
        stock = inventory['xbl'][variant]
        if hashlib.sha256((args.stock / (variant + '.img')).read_bytes()).hexdigest() != stock['sha256']:
            raise ValueError('stock partition changed')
        records, unresolved = [], {g: [] for g in UNRESOLVED}
        for module in stock['modules']:
            for section in module['sections']:
                data = read_section(module, section['kind'])
                for g in UNRESOLVED:
                    if uuid.UUID(g).bytes_le in data:
                        unresolved[g].append({'name': module['name'], 'guid': module['guid'], 'kind': section['kind']})
                if section['kind'] not in ('pe32', 'te'):
                    continue
                mapped = sections(data, section['kind'])
                targets, occurrences = {}, []
                for mapped_section in mapped:
                    for name, needle in needles.items():
                        offset = mapped_section['data'].find(needle)
                        while offset >= 0:
                            address = mapped_section['address'] + offset
                            targets[address] = name
                            occurrences.append({'name': name, 'address': address,
                                                'file_offset': mapped_section['offset'] + offset})
                            offset = mapped_section['data'].find(needle, offset + 1)
                if occurrences:
                    records.append({'name': module['name'], 'guid': module['guid'], 'kind': section['kind'],
                                    'sha256': section['sha256'], 'occurrences': occurrences,
                                    'constant_references': references(mapped, targets)})
        result['variants'][variant] = {'xbl_sha256': stock['sha256'], 'modules': records,
                                       'unresolved_guid_section_hits': unresolved}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    for v, r in result['variants'].items():
        print(v, len(r['modules']), 'images contain HOB/kernel GUIDs;', sum(len(m['constant_references']) for m in r['modules']), 'bounded basic-block address references')


if __name__ == '__main__': main()
