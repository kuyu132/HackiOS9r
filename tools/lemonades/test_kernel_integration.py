"""Structural integration assertions supplement compiled policy/adapter tests."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class KernelIntegrationTests(unittest.TestCase):
    def test_guards_precede_driver_side_effects(self):
        drivers = ['cpufreq', 'goodix', 'buttons', 'battery', 'ufs', 'adreno', 'wifi',
                   'adsp', 'speaker', 'haptic', 'torch', 'camera',
                   'virtio_input', 'virtio_net', 'virtio_blk', 'virtio_sound']
        for driver in drivers:
            with self.subTest(driver=driver):
                source = (ROOT / f'xnu/files/bsd/dev/redwood_{driver}.c').read_text()
                cap = 'VIRTIO_MMIO' if driver.startswith('virtio_') else 'REDWOOD_HW'
                self.assertRegex(source, rf'redwood_{driver}_init\(void\)\s*\{{\s*'
                    rf'if \(!hackios_platform_allows\(HACKIOS_CAP_{cap}\)\)\s*\{{\s*return;')

    def test_staging_and_kernel_registration(self):
        patch = (ROOT / 'xnu/redwood.patch').read_text()
        apply = (ROOT / 'xnu/apply.sh').read_text()
        for module in ['report', 'input', 'tcm', 'session', 'geni', 'transport']:
            self.assertIn(f'+bsd/dev/lemonades/s3908_{module}.c standard', patch)
            self.assertTrue((ROOT / f'common/lemonades/s3908_{module}.c').is_file())
        self.assertIn('s3908_{report,input,tcm,session,geni,transport}.{c,h}', apply)
        self.assertIn('+bsd/dev/lemonades_touch.c standard', patch)
        self.assertIn('+bsd/dev/lemonades_touch_platform.c standard', patch)

    def test_loader_identity_and_probe_block(self):
        loader = (ROOT / 'xnuloader/loader.c').read_text()
        self.assertIn('dt_prop_str(&w, "hackios,board", plat->name);', loader)
        # The diagnostic target still cannot invoke XNU.
        run = loader[loader.index('run_kernel('):]
        self.assertRegex(run, r'(?s)#ifdef HACKIOS_LEMONADES_PROBE.*?return 0;.*?#endif')


if __name__ == '__main__':
    unittest.main()
