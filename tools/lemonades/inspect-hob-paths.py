#!/usr/bin/env python3
"""Recheck reviewed H.30 SEC/EnvDxe HOB paths; never recover live addresses."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import uuid
from protocol_audit import read_section

spec = importlib.util.spec_from_file_location('hob_trace', Path(__file__).with_name('trace-hobs.py'))
trace = importlib.util.module_from_spec(spec); spec.loader.exec_module(trace)
# Each digest pins an entire reviewed instruction range, not a pattern used to
# discover/execute pointers. A firmware change requires a new manual review.
SEC = [
    ('scheduler_configuration_gate_and_startup', 0x9fc21650, 0x148, '569398d9443651fa12778d57351c6ce49030c50e3b72d37774d2c74aad3a842d'),
    ('shim_registration', 0x9fc1690c, 0xf0, 'da45e0ffec7f661f588c2fba00dcebabc2e99748bef1a8efe983c903a2b64c0d'),
    ('scheduler_pointer_hob', 0x9fc2748c, 0x30, '599fc20b0ba2e210de7ccf238cca7c791c583da18c27ae105a7346f0b0b63212'),
    ('guid_hob_allocate_and_copy', 0x9fc15fa8, 0xb8, 'a9319a807a91d5a97757dc4b91f12bce92594d5de77af011fe7ca56df14d3ef4'),
    ('shim_pointer_hob', 0x9fc16b10, 0x88, '79027cb1b9f3e6ad690e74bf876a71432bd95a48f35283b9c2023bcc7dfbbe10'),
    ('shim_load_version_selection', 0x9fc169fc, 0x114, '400f445f66a85e18f4f9aeae2322b8d23e8e5eaf12c58af79edb1e84046fe061'),
]
ENV = [
    ('kernel_locate_and_scheduler_hob_fallback', 0x8834, 0xec, 'f8e15a3bc225cdffb6724ff785cb42e11d6827f38740b8e1032d6f8d69c97e0b'),
    ('serial_shim_load_version_zero', 0x3c20, 0x60, '996620ea453b772d592bf9316cfd6252fffc8ebccc19cc6c9053742e4dfb8ce2'),
    ('config_shim_load_version_zero', 0x3e4c, 0x60, 'e656edebf7e42eb62df3d448757da12a07f0c6ed34d389af5105faa006d95bed'),
    ('shim_hob_reader', 0xc888, 0x24, '9579266c407fb8881af190984686d1a873183b215f7f6ed3ecb512c488dfe27e'),
]
SCHEDULER = [0x10005, 0x9fc34418, 0x9fc34578, 0x9fc344d8, 0x9fc34438,
             0x9fc34478, 0x9fc344a8, 0x9fc3d1b8, 0x9fc34598, 0x9fc34608, 0x9fc05ca0, 0x9fc34638]


def read_at(mapped, address, length):
    for section in mapped:
        offset = address - section['address']
        if offset >= 0 and length >= 0 and offset + length <= len(section['data']):
            return section['data'][offset:offset + length]
    raise ValueError(f'unmapped initialized data: {address:#x}+{length:#x}')


def verify_ranges(mapped, ranges):
    result = []
    for label, address, length, expected in ranges:
        data = read_at(mapped, address, length)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'{label}: reviewed instructions changed; new review required')
        result.append({'label': label, 'address': address, 'length': length, 'sha256': expected,
                       'bytes': data.hex()})
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stock', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    inv = json.loads((args.stock / 'analysis/inventory.json').read_text())
    result = {'scope': 'Static preferred addresses in original binaries only; no preserved/live scheduler established', 'variants': {}}
    for variant in ('xbl', 'xbl_lp5'):
        original = inv['xbl'][variant]
        if hashlib.sha256((args.stock / (variant+'.img')).read_bytes()).hexdigest() != original['sha256']:
            raise ValueError('stock partition changed')
        records = {}
        for label, guid, kind, ranges in [
            ('SEC', '8AF09F13-44C5-96EC-1437-DD899CB5EE5D', 'te', SEC),
            ('EnvDxe', '90A49AFD-422F-08AE-9611-E788D3804845', 'pe32', ENV)]:
            module = next(m for m in original['modules'] if m['guid'] == guid)
            data = read_section(module, kind); mapped = trace.sections(data, kind)
            records[label] = {'guid': guid, 'sha256': hashlib.sha256(data).hexdigest(),
                              'ranges': verify_ranges(mapped, ranges)}
            callers = [(0x9fc0d65c, 0x9fc21650), (0x9fc21730, 0x9fc2748c), (0x9fc0d9c0, 0x9fc16b10)] if label == 'SEC' else [(0x1450, 0x8834)]
            for caller, target in callers:
                expected = 0x94000000 | (((target - caller) // 4) & 0x3ffffff)
                if read_at(mapped, caller, 4) != struct.pack('<I', expected):
                    raise ValueError('reviewed direct call changed')
            records[label]['direct_calls'] = [{'address': a, 'target': t} for a, t in callers]
            addresses = {'Scheduler': 0x9fc34210, 'Shim': 0x9fc34250} if label == 'SEC' else {
                'Scheduler': 0x12254, 'Shim': 0x12078, 'KernelProtocol': 0x121f8}
            for name, address in addresses.items():
                if read_at(mapped, address, 16) != uuid.UUID(trace.HOBS[name]).bytes_le:
                    raise ValueError(f'{label}: {name} GUID changed')
            if label == 'SEC':
                table = list(struct.unpack('<12Q', read_at(mapped, 0x9fc34660, 96)))
                if table != SCHEDULER:
                    raise ValueError('scheduler table changed')
                shim = list(struct.unpack('<3Q', read_at(mapped, 0x9fc34310, 24)))
                if shim != [0x10001, 0x9fc1690c, 0x9fc169fc]:
                    raise ValueError('shim table changed')
                records[label]['scheduler_table'] = table
                records[label]['shim_table'] = shim
                records[label]['scheduler_table_in_replacement_fd_range'] = 0x9fc00000 <= 0x9fc34660 < 0x9ff00000
                for address, name in [(0x9fc31875, b'EnableMultiThreading\0'), (0x9fc3188a, b'Sched Heap\0'),
                                      (0x9fc31895, b'MaxCoreCnt\0'), (0x9fc318a0, b'EarlyInitCoreCnt\0')]:
                    if read_at(mapped, address, len(name)) != name:
                        raise ValueError('Scheduler configuration key changed')
            else:
                for address, name in [(0xd7d0, b'SerialPort Lib\0'), (0xd7df, b'UEFI Config Lib\0')]:
                    if read_at(mapped, address, len(name)) != name:
                        raise ValueError('EnvDxe Shim name changed')
        config = next(m for m in original['modules'] if m['guid'] == 'DDE58710-41CD-4306-DBFB-3FA90BB1D2DD')
        raw = read_section(config, 'raw')
        config_hash = hashlib.sha256(raw).hexdigest()
        if config_hash != 'bda60d665d04a9ebf3bc16e4af64b1221f4a43bbc23d4dfa05165dad1519b9c7':
            raise ValueError('stock scheduler configuration changed; review required')
        config_values = {'EnableMultiThreading': 1, 'MaxCoreCnt': 8, 'EarlyInitCoreCnt': 1}
        for key, value in config_values.items():
            if (key + ' = ' + str(value)).encode() not in raw.splitlines():
                raise ValueError('reviewed configuration value absent')
        result['variants'][variant] = {'xbl_sha256': original['sha256'], 'modules': records,
            'stock_configuration': {'sha256': config_hash, 'values': config_values,
                'scheduler_heap': {'address': 0x9bc00000, 'size': 0x400000},
                'limit': 'Configuration enables stock path; does not initialize a scheduler in replacement Mu SEC'}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print('Both variants match reviewed SEC pointer HOB construction, scheduler 1.5 and EnvDxe fallback/Shim paths')


if __name__ == '__main__': main()
