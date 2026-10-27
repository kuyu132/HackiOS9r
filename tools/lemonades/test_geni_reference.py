import unittest
from geni_reference import collect, compare, ROOT

class GeniSourceContractTests(unittest.TestCase):
    def test_pinned_register_and_board_contract(self):
        report=collect()
        self.assertEqual(report['matched_registers'],24)
        self.assertEqual(report['matched_irq_bits'],8)
        self.assertEqual(report['profile']['physical_base'],'0xa94000')

    def test_changed_register_rejected(self):
        from lineage import pinned_text
        header=pinned_text('kernel','kernel-sm8250','include/linux/qcom-geni-se.h')
        driver=pinned_text('kernel','kernel-sm8250','drivers/i2c/busses/i2c-qcom-geni.c')
        local=(ROOT/'common/lemonades/s3908_geni.h').read_text().replace('SG_RX_FIFO=0x780','SG_RX_FIFO=0x788')
        with self.assertRaisesRegex(ValueError,'SG_RX_FIFO'):
            compare(local,header+'\n'+driver)

if __name__=='__main__': unittest.main()
