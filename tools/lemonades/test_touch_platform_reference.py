import unittest
from touch_platform_reference import ROOT, PATHS, collect, compare, pinned_text

class TouchPlatformReferenceTests(unittest.TestCase):
    def test_addresses_derived_from_pinned_sources(self):
        report = collect()
        self.assertEqual(report['addresses']['LTP_GPIO_PA'], '0xf524000')
        self.assertEqual(report['addresses']['LTP_GCC_VOTE_PA'], '0x150000')

    def test_wrong_gpio_bank_rejected(self):
        source = {p:pinned_text('kernel','kernel-sm8250',p) for p in PATHS}
        local = (ROOT/'xnu/files/bsd/dev/lemonades_touch_platform.c').read_text()
        with self.assertRaisesRegex(ValueError, 'LTP_GPIO_PA'):
            compare(local.replace('0xf524000','0xf024000'),source)

if __name__ == '__main__': unittest.main()
