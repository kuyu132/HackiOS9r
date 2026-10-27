#!/usr/bin/env python3
"""Check the reviewed H.30 USB protocol table and installation instruction bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import uuid
import pefile
from protocol_audit import read_section

USB_GUID = uuid.UUID('D9D9CE48-44B8-4F49-8E3E-2A3B927DC6C1')
TABLE_RVA = 0xe0d8
# Reviewed llvm-objdump instructions, not a signature used to patch firmware.
INSTALL = {0x1210: 0x94000090, 0x1450: 0x140002d7,
           0x1fb8: 0xb0000068, 0x1fbc: 0xb0000061, 0x1fc0: 0xb0000062,
           0x1fc4: 0xf9420d09, 0x1fc8: 0x9102a021, 0x1fcc: 0x91036042,
           0x1fd0: 0xaa1f03e3, 0x1fd4: 0xf940a528, 0x1fd8: 0xf90007e0,
           0x1fdc: 0x910023e0, 0x1fe0: 0xd63f0100}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stock', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    inv = json.loads((args.stock / 'analysis/inventory.json').read_text())
    result = {}
    for variant in ('xbl', 'xbl_lp5'):
        modules = inv['xbl'][variant]['modules']
        driver = next(m for m in modules if m['guid'] == '3299A266-15F0-4346-8318-716336736D3E')
        data = read_section(driver, 'pe32')
        pe = pefile.PE(data=data)
        if pe.FILE_HEADER.Machine != 0xaa64 or pe.OPTIONAL_HEADER.ImageBase != 0:
            raise ValueError('different USB image layout; needs new review')
        table = struct.unpack('<10Q', pe.get_data(TABLE_RVA, 80))
        if table[0] != 0x10000001 or pe.get_data(0xe0a8, 16) != USB_GUID.bytes_le:
            raise ValueError('reviewed protocol table/GUID changed')
        for address in table[1:]:
            section = pe.get_section_by_rva(address)
            if section is None or not section.Characteristics & 0x20000000:
                raise ValueError('protocol function outside executable section')
        for address, instruction in INSTALL.items():
            if pe.get_data(address, 4) != struct.pack('<I', instruction):
                raise ValueError(f'{variant}: reviewed installation instruction changed at {address:#x}')
        result[variant] = {'sha256': hashlib.sha256(data).hexdigest(), 'table_rva': TABLE_RVA,
                           'revision': table[0], 'protocol_guid': str(USB_GUID).upper(),
                           'functions_rva': dict(zip(('Start', 'Send', 'HandleEvent', 'AllocateTransferBuffer',
                                                     'FreeTransferBuffer', 'Stop', 'AbortXfer', 'SetEndpointStallState', 'StartEx'), table[1:])),
                           'reviewed_install_instructions': {hex(k): hex(v) for k, v in INSTALL.items()},
                           'limits': 'Static table and install call-site evidence only; no execution, controller or cable validation.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('Both stock variants match the reviewed USB ABI and install instruction sequence')


if __name__ == '__main__':
    main()
