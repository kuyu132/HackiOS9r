"""Run only reviewed stock Shim routines in isolated synthetic AArch64 RAM.

No host/device MMIO is mapped. This is not SEC boot, HOB handoff or hardware
validation. Original code/section hashes and bounded execution are mandatory.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_LR, UC_ARM64_REG_SP, UC_ARM64_REG_PC
from protocol_audit import read_section

spec = importlib.util.spec_from_file_location('hob_paths', Path(__file__).with_name('inspect-hob-paths.py'))
paths = importlib.util.module_from_spec(spec); spec.loader.exec_module(paths)
ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'out/lemonades/stock/LE2101_14.0.0.2301'
REGISTRY = 0x9fc3b468
ERROR = 1 << 63
REVIEWED_TE = {
    'xbl': '4afdd98f177bb418d4009af98bba2f9780b8641d853889d252047cc6a1726592',
    'xbl_lp5': '319888c00f7a549030c7997d5ca0ff59aca8d8444f6915f7ddce9233591f5003',
}


def stock_image(variant, stock=STOCK):
    original = json.loads((stock/'analysis/inventory.json').read_text())['xbl'][variant]
    if hashlib.sha256((stock/(variant+'.img')).read_bytes()).hexdigest() != original['sha256']:
        raise ValueError('stock partition changed')
    module = next(m for m in original['modules'] if m['guid']=='8AF09F13-44C5-96EC-1437-DD899CB5EE5D')
    data = read_section(module, 'te'); mapped = paths.trace.sections(data, 'te')
    if hashlib.sha256(data).hexdigest() != REVIEWED_TE[variant]:
        raise ValueError('SEC differs from reviewed Shim emulator input')
    paths.verify_ranges(mapped, paths.SEC)
    return data, mapped


class StockShim:
    def __init__(self, mapped):
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.uc.mem_map(0x9fc00000, 0x40000)
        for section in mapped:
            self.uc.mem_write(section['address'], section['data'])
        # Make code read/execute only; all remaining image pages read/write,
        # non-executable. Unexpected firmware calls cannot reach MMIO.
        self.uc.mem_protect(0x9fc00000, 0x40000, UC_PROT_READ | UC_PROT_WRITE)
        for section in mapped:
            if section['executable']:
                start = section['address'] & ~0xfff
                end = (section['address']+len(section['data'])+0xfff)&~0xfff
                self.uc.mem_protect(start, end-start, UC_PROT_READ | UC_PROT_EXEC)
        self.uc.mem_map(0x10000000, 0x10000, UC_PROT_READ | UC_PROT_WRITE)
        self.uc.mem_map(0x20000000, 0x10000, UC_PROT_READ | UC_PROT_WRITE)
        self.uc.mem_map(0x30000000, 0x1000, UC_PROT_READ | UC_PROT_EXEC)
        # Synthetic empty registry with the original layout/capacity; do not
        # run the Shim initializer, which allocates a real firmware HOB.
        self.uc.mem_write(REGISTRY, bytes(0x720))
        self.uc.mem_write(REGISTRY, struct.pack('<I', 0x10001))
        self.uc.mem_write(REGISTRY+0x310, struct.pack('<QQ', REGISTRY+0x320, REGISTRY+0x720))

    def call(self, address, *args):
        for reg, value in zip((UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2), args):
            self.uc.reg_write(reg, value)
        self.uc.reg_write(UC_ARM64_REG_SP, 0x1000fff0)
        self.uc.reg_write(UC_ARM64_REG_LR, 0x30000000)
        self.uc.emu_start(address, 0x30000000, timeout=1000000, count=100000)
        if self.uc.reg_read(UC_ARM64_REG_PC) != 0x30000000:
            raise ValueError('stock routine did not return within instruction/time budget')
        return self.uc.reg_read(UC_ARM64_REG_X0)

    def name(self, name):
        raw = name.encode('ascii')+b'\0'
        if len(raw)>0x8000: raise ValueError('name exceeds synthetic input memory')
        self.uc.mem_write(0x20000000, raw)
        return 0x20000000

    def install(self, name, version, interface):
        return self.call(0x9fc1690c, self.name(name), version, interface)

    def load(self, name, version):
        self.uc.mem_write(0x2000f000, bytes(8))
        status = self.call(0x9fc169fc, self.name(name), version, 0x2000f000)
        return status, struct.unpack('<Q', self.uc.mem_read(0x2000f000,8))[0]
