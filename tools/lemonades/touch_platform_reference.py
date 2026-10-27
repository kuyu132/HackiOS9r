"""Derive mapped windows from the pinned SM8250 source, without device access."""
import hashlib
import json
from pathlib import Path
import re
from lineage import pinned_text, PINS

ROOT = Path(__file__).resolve().parents[2]
PATHS = [
    'arch/arm64/boot/dts/vendor/qcom/kona.dtsi',
    'arch/arm64/boot/dts/vendor/qcom/kona-pinctrl.dtsi',
    'arch/arm64/boot/dts/vendor/qcom/kona-qupv3.dtsi',
    'drivers/pinctrl/qcom/pinctrl-kona.c',
    'drivers/clk/qcom/gcc-kona.c',
    'drivers/clk/qcom/clk-branch.c',
]

def number(pattern, text):
    match = re.search(pattern, text)
    if not match:
        raise ValueError('missing source contract: ' + pattern)
    return int(match[1], 0)

def compare(local, source):
    soc, pins, qup, pin_driver, gcc, branch = [source[p] for p in PATHS]
    gcc_base = number(r'clock_gcc:.*?reg\s*=\s*<(0x[\da-f]+)', soc.replace('\n',' '))
    tlmm_base = number(r'tlmm:.*?reg\s*=\s*<(0x[\da-fA-F]+)', pins.replace('\n',' '))
    south = number(r'#define SOUTH\s+(0x[\da-f]+)', pin_driver)
    stride = number(r'#define REG_SIZE\s+(0x[\da-f]+)', pin_driver)
    se = qup.split('qupv3_se13_i2c:', 1)[1].split('};',1)[0]
    se_base = number(r'reg\s*=\s*<(0x[\da-f]+)', se)
    size = number(r'reg\s*=\s*<0x[\da-f]+ (0x[\da-f]+)>', se)
    branches = {}
    for name, suffix, bit in [('LTP_S5','wrap1_s5',27), ('LTP_MAHB','wrap_1_m_ahb',20),
                              ('LTP_SAHB','wrap_1_s_ahb',21)]:
        block = gcc.split('static struct clk_branch gcc_qupv3_'+suffix+'_clk = {',1)[1].split('\n};',1)[0]
        offset = number(r'\.halt_reg = (0x[\da-f]+)', block)
        vote = number(r'\.enable_reg = (0x[\da-f]+)', block)
        actual_bit = number(r'\.enable_mask = BIT\((\d+)\)', block)
        if actual_bit != bit or vote != 0x52008:
            raise ValueError('clock vote contract changed: '+suffix)
        branches[name] = gcc_base + offset
    branch_page = branches['LTP_MAHB'] & ~(size-1)
    vote_pa = gcc_base + vote
    vote_page = vote_pa & ~(size-1)
    expected = {'LTP_WINDOW':size, 'LTP_GCC_BRANCH_PA':branch_page, 'LTP_GCC_VOTE_PA':vote_page,
        'LTP_GPIO_PA':tlmm_base + south + 36*stride, 'LTP_SE_PA':se_base, 'LTP_VOTE':vote_pa-vote_page,
        **{k:v-branch_page for k,v in branches.items()}}
    for name, value in expected.items():
        if number(r'\b'+name+r'\s*=\s*(0x[\da-f]+)', local) != value:
            raise ValueError('platform address mismatch: '+name)
    # Check the layout assumptions used by the direct GPIO snapshots as well.
    for pin in range(36,40):
        if not re.search(r'PINGROUP\('+str(pin)+r', SOUTH, qup13,',pin_driver):
            raise ValueError('GPIO bank/function changed')
    patterns = [r'\.ctl_reg = base \+ REG_SIZE \* id', r'\.io_reg = base \+ 0x4 \+ REG_SIZE \* id',
                r'\.mux_bit = 2', r'\.oe_bit = 9', r'\.in_bit = 0', r'\.out_bit = 1',
                r'msm_mux_gpio, /\* gpio mode \*/\s*\\\s*msm_mux_##f1,']
    if not all(re.search(p,pin_driver) for p in patterns):
        raise ValueError('GPIO register layout changed')
    if number(r'#define BRANCH_CLK_OFF\s+BIT\((\d+)\)',branch) != 31:
        raise ValueError('clock branch status changed')
    return expected

def collect():
    source = {p:pinned_text('kernel','kernel-sm8250',p) for p in PATHS}
    local = (ROOT/'xnu/files/bsd/dev/lemonades_touch_platform.c').read_text()
    addresses = compare(local,source)
    return {'source':PINS['kernel'], 'addresses':{k:hex(v) for k,v in addresses.items()},
        'files_sha256':{p:hashlib.sha256(s.encode()).hexdigest() for p,s in source.items()},
        'limits':['Read-only source verification; no physical hardware accessed.',
                  'Clock votes and CLK_OFF snapshot do not prove parent rate, rails or ownership.']}

if __name__ == '__main__':
    target=ROOT/'out/lemonades/touch-platform/reference.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(collect(),indent=2)+'\n')
    print(target)
