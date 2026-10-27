"""Source provenance and execution of the generated Mu packaging function."""
import ast
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from lineage import ROOT, PINS, collect, load_profile, patch_mu_wrapper


class LineageTests(unittest.TestCase):
    def test_profile_reproduces_from_pinned_device_sources(self):
        profile, report = collect()
        self.assertEqual(profile, load_profile())
        self.assertIn('OnePlus9R', report['board_info'])
        common = report['firmware_inventory'][1]
        self.assertIn('8T', common['upstream_origin_note'])
        self.assertIn('odm/firmware/tp/20828/FW_S3908_SAMSUNG.img', common['selected_entries'])

    def test_mu_wrapper_preserves_zero_base_and_separate_dtb(self):
        source = subprocess.check_output(['git', '-C', str(ROOT / 'Mu-Silicium'), 'show',
                                          PINS['mu']['commit'] + ':build_uefi.py'], text=True)
        tree = ast.parse(patch_mu_wrapper(source))
        # Execute only the real packaging function; avoid invoking Mu's CLI/build environment.
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'create_android_boot_img')
        unit = ast.Module(body=[function], type_ignores=[])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fv = root / 'lemonadesPkg/RELEASE_CLANGPDB/FV'
            fv.mkdir(parents=True)
            (fv / 'SILICIUM_UEFI.fd').write_bytes(b'synthetic-fd')
            (root / 'BootShim.bin').write_bytes(b'synthetic-shim')
            (root / 'mkbootimg.py').touch()
            run = Mock(return_value=SimpleNamespace(returncode=0))
            namespace = dict(BuildContext=SimpleNamespace, BUILD_PATH=root, RESOURCE_DTBS_PATH=root,
                             RESOURCE_SCRIPTS_PATH=root, BOOT_SHIM_PATH=root, sys=sys, shutil=shutil,
                             gzip=gzip, logger=Mock(), subprocess=SimpleNamespace(run=run))
            exec(compile(unit, '<generated Mu packaging function>', 'exec'), namespace)
            context = SimpleNamespace(device='lemonades', device_model='9R', build_mode='RELEASE')
            config = load_profile()['boot_image'] | {'dtb': 'Resources/DTBs/lemonades.dtb'}
            self.assertTrue(namespace[function.name](context,
                {'kernel_compression': 'gzip', 'append_dtb': False}, config, True, False))
            command = run.call_args.args[0]
            for flag, value in [('--base', '0'), ('--pagesize', '4096'), ('--header_version', '2'),
                                ('--dtb', 'Resources/DTBs/lemonades.dtb')]:
                self.assertEqual(command[command.index(flag) + 1], value)
            kernel = (root / 'lemonadesPkg/lemonades-kernel').read_bytes()
            self.assertEqual(gzip.decompress(kernel), b'synthetic-shimsynthetic-fd')


if __name__ == '__main__':
    unittest.main(verbosity=2)
