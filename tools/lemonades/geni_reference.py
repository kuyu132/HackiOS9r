"""Compare the prepared FIFO backend's register contract with pinned primary sources."""
import hashlib
import json
from pathlib import Path
import re
from lineage import pinned_text, PINS
ROOT = Path(__file__).resolve().parents[2]
OFFSETS = {
    'SG_STATUS':'SE_GENI_STATUS', 'SG_FIFO_DISABLE':'GENI_IF_FIFO_DISABLE_RO',
    'SG_FW':'GENI_FW_REVISION_RO', 'SG_DMA':'SE_GENI_DMA_MODE_EN',
    'SG_TX_PACK0':'SE_GENI_TX_PACKING_CFG0', 'SG_TX_PACK1':'SE_GENI_TX_PACKING_CFG1',
    'SG_RX_PACK0':'SE_GENI_RX_PACKING_CFG0', 'SG_RX_PACK1':'SE_GENI_RX_PACKING_CFG1',
    'SG_TX_LEN':'SE_I2C_TX_TRANS_LEN', 'SG_RX_LEN':'SE_I2C_RX_TRANS_LEN',
    'SG_CMD':'SE_GENI_M_CMD0', 'SG_CTRL':'SE_GENI_M_CMD_CTRL_REG',
    'SG_IRQ':'SE_GENI_M_IRQ_STATUS', 'SG_IRQ_EN':'SE_GENI_M_IRQ_EN', 'SG_CLEAR':'SE_GENI_M_IRQ_CLEAR',
    'SG_TX_FIFO':'SE_GENI_TX_FIFOn', 'SG_RX_FIFO':'SE_GENI_RX_FIFOn',
    'SG_TX_STATUS':'SE_GENI_TX_FIFO_STATUS', 'SG_RX_STATUS':'SE_GENI_RX_FIFO_STATUS',
    'SG_TX_WM':'SE_GENI_TX_WATERMARK_REG', 'SG_RX_WM':'SE_GENI_RX_WATERMARK_REG',
    'SG_GSI':'SE_GSI_EVENT_EN', 'SG_HW_TX':'SE_HW_PARAM_0', 'SG_HW_RX':'SE_HW_PARAM_1',
}
BITS = {'SG_DONE':'M_CMD_DONE_EN', 'SG_CANCEL':'M_CMD_CANCEL_EN', 'SG_ABORT':'M_CMD_ABORT_EN',
        'SG_NACK':'M_GP_IRQ_1_EN', 'SG_ARB':'M_GP_IRQ_4_EN', 'SG_RX_WATERMARK':'M_RX_FIFO_WATERMARK_EN',
        'SG_RX_LAST':'M_RX_FIFO_LAST_EN', 'SG_TX_WATERMARK':'M_TX_FIFO_WATERMARK_EN'}

def compare(local, primary):
    for name, upstream in OFFSETS.items():
        a = re.search(r'\b' + name + r'\s*=\s*(0x[0-9a-fA-F]+)', local)
        b = re.search(r'^#define\s+' + upstream + r'\s+\((0x[0-9a-fA-F]+)\)', primary, re.M)
        if not a or not b or int(a[1], 16) != int(b[1], 16):
            raise ValueError('register mismatch: ' + name)
    for name, upstream in BITS.items():
        a = re.search(r'^#define\s+' + name + r'\s+\(1u << (\d+)\)', local, re.M)
        b = re.search(r'^#define\s+' + upstream + r'\s+\(?BIT\((\d+)\)', primary, re.M)
        if not a or not b or a[1] != b[1]:
            raise ValueError('IRQ bit mismatch: ' + name)

def collect():
    paths = ['include/linux/qcom-geni-se.h', 'drivers/i2c/busses/i2c-qcom-geni.c',
             'drivers/platform/msm/qcom-geni-se.c', 'arch/arm64/boot/dts/vendor/qcom/kona-qupv3.dtsi',
             'arch/arm64/boot/dts/vendor/qcom/kona-pinctrl.dtsi',
             'arch/arm64/boot/dts/vendor/oplus/lemonades/kona-mtp.dtsi']
    sources = {p:pinned_text('kernel', 'kernel-sm8250', p) for p in paths}
    primary = sources[paths[0]] + '\n' + sources[paths[1]]
    local = (ROOT / 'common/lemonades/s3908_geni.h').read_text()
    compare(local, primary)
    # Scope the literal checks to the selected engine and touch node.
    controller = sources[paths[3]].split('qupv3_se13_i2c:')[1].split('};',1)[0]
    pins = sources[paths[4]].split('qupv3_se13_i2c_active:')[1].split('qupv3_se13_i2c_sleep:')[0]
    touch = sources[paths[5]].split('synaptics@4B')[1].split('};',1)[0]
    for text, patterns in [(controller, [r'reg\s*=\s*<0xa94000 0x4000>', r'GIC_SPI 358',
            r'GCC_QUPV3_WRAP1_S5_CLK', r'GCC_QUPV3_WRAP_1_M_AHB_CLK',r'GCC_QUPV3_WRAP_1_S_AHB_CLK']),
        (pins,[r'"gpio36", "gpio37"',r'function\s*=\s*"qup13"']),
        (touch,[r'reg\s*=\s*<0x4B>',r'irq-gpio\s*=\s*<&tlmm 39 0x2008>',
            r'reset-gpio\s*=\s*<&tlmm 38 0x1>',r'vdd_2v8-supply\s*=\s*<&pm8150_l13>',
            r'vcc_1v8-supply\s*=\s*<&pm8150a_l1>',r'vdd_2v8_volt\s*=\s*<3008000>'])]:
        for pattern in patterns:
            if not re.search(pattern,text): raise ValueError('device source contract changed: '+pattern)
    return {'source':PINS['kernel'],'files_sha256':{p:hashlib.sha256(v.encode()).hexdigest() for p,v in sources.items()},
        'matched_registers':len(OFFSETS),'matched_irq_bits':len(BITS),
        'profile':{'engine':'qupv3_se13_i2c','physical_base':'0xa94000','mmio_size':'0x4000',
                   'address':'0x4b','sda_scl_gpio':[36,37],'reset_gpio':38,'attention_gpio':39,
                   'attention_flags':'0x2008','gic_spi':358,'vdd_2v8_microvolts':3008000,
                   'rails':['pm8150_l13','pm8150a_l1']},
        'limits':['Prepared FIFO access only; resources/MMIO/clock/pinmux/IRQ must be supplied externally.',
                  'No physical registers accessed by this script; no hardware readiness inferred from DTS.']}

if __name__ == '__main__':
    report=collect()
    out=ROOT/'out/lemonades/geni/reference.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(out)
