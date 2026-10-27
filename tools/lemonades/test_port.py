"""Host regressions for target isolation and boot-image byte layout (no devices used)."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hackios-packer-test-')
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.output = self.dir / 'test-only.img'
        self.env = {k: v for k, v in os.environ.items() if k not in (
            'UEFI_TARGET', 'UEFI_FD', 'BOOT_SHIM', 'DTB', 'FD_BASE', 'FD_SIZE', 'PAYLOAD_BASE')}
        self.env['UEFI_TARGET'] = 'lemonades'

    def pack(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'mkxnuimg.py'), '-o', str(self.output), *args],
                              env=self.env, capture_output=True, text=True)

    def fixture(self):
        # Synthetic bytes, used only to verify packaging; not firmware.
        self.shim = self.dir / 'BootShim.bin'
        self.shim.write_bytes(b'TESTSHIM' + struct.pack('<QQ', 0x9FC00000, 4096) + bytes(32) + b'ARM\x64' + bytes(4))
        self.fd = self.dir / 'uefi.fd'
        self.fd.write_bytes(b'TEST FD' + bytes(4096 - 7))
        self.dtb = self.dir / 'device.dtb'
        dts = self.dir / 'device.dts'
        dts.write_text('/dts-v1/; / { model = "packaging-test-only"; };')
        subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(self.dtb), str(dts)], check=True)
        self.meta = {'target': 'lemonades', 'fd_base': 0x9FC00000, 'fd_size': 4096,
                     'payload_base': None, 'sha256': hashlib.sha256(self.shim.read_bytes()).hexdigest()}
        Path(str(self.shim) + '.json').write_text(json.dumps(self.meta))
        self.env.update(UEFI_FD=str(self.fd), DTB=str(self.dtb), BOOT_SHIM=str(self.shim),
                        FD_BASE='0x9FC00000', FD_SIZE='0x1000')

    def refused(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertFalse(self.output.exists())

    def test_no_cross_device_fallback(self):
        self.refused(self.pack(), 'no redwood fallback')

    def test_partial_device_inputs_are_not_enough(self):
        self.fixture()
        del self.env['BOOT_SHIM']
        self.refused(self.pack(), 'BOOT_SHIM')

    def test_wrong_target_or_addresses_or_hash_are_rejected(self):
        self.fixture()
        for field, value in (('target', 'redwood'), ('fd_base', 0x9FD00000),
                             ('fd_size', 0x200000), ('payload_base', 0xF0000000), ('sha256', 'wrong')):
            with self.subTest(field=field):
                changed = dict(self.meta, **{field: value})
                Path(str(self.shim) + '.json').write_text(json.dumps(changed))
                self.refused(self.pack(), 'boot shim metadata does not match')

    def test_missing_shim_manifest(self):
        self.fixture()
        Path(str(self.shim) + '.json').unlink()
        self.refused(self.pack(), 'missing/invalid boot shim metadata')

    def test_header_and_metadata_must_agree(self):
        self.fixture()
        binary = bytearray(self.shim.read_bytes())
        struct.pack_into('<Q', binary, 8, 0x9FD00000)
        self.shim.write_bytes(binary)
        self.meta['sha256'] = hashlib.sha256(binary).hexdigest()
        Path(str(self.shim) + '.json').write_text(json.dumps(self.meta))
        self.refused(self.pack(), 'ARM64 header does not match')

    def test_no_xnu_payload_until_memory_map_is_validated(self):
        self.fixture()
        payload = self.dir / 'payload.bin'
        payload.write_bytes(b'XNUP' + struct.pack('<I', 24) + bytes(24))
        self.refused(self.pack('-p', str(payload)), 'only the payload-free UEFI probe')

    def test_fd_size_must_match_shim(self):
        self.fixture()
        self.fd.write_bytes(bytes(8192))
        self.refused(self.pack(), 'UEFI FD has')

    def test_concatenated_dtb_rejected(self):
        self.fixture()
        self.dtb.write_bytes(self.dtb.read_bytes() * 2)
        self.refused(self.pack(), 'one complete tree')

    def test_non_dtb_rejected(self):
        self.fixture()
        self.dtb.write_bytes(bytes(40))
        self.refused(self.pack(), 'not a flattened device tree')

    def test_pack_preserves_selected_bytes(self):
        self.fixture()
        result = self.pack()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.output.read_bytes()
        self.assertEqual(data[:8], b'ANDROID!')
        kernel_size = struct.unpack_from('<I', data, 8)[0]
        page_size = struct.unpack_from('<I', data, 36)[0]
        self.assertEqual(page_size, 4096)
        self.assertEqual(struct.unpack_from('<I', data, 40)[0], 2)  # boot header v2
        self.assertEqual(struct.unpack_from('<I', data, 12)[0], 0x8000)  # base=0 + bundled default offset
        self.assertEqual(struct.unpack_from('<I', data, 1644)[0], 1660)
        kernel = data[page_size:page_size + kernel_size]
        dtb = self.dtb.read_bytes()
        self.assertEqual(gzip.decompress(kernel), self.shim.read_bytes() + self.fd.read_bytes())
        self.assertEqual(struct.unpack_from('<I', data, 1648)[0], len(dtb))
        self.assertEqual(struct.unpack_from('<Q', data, 1652)[0], 0x1f00000)
        ramdisk_size = struct.unpack_from('<I', data, 16)[0]
        dtb_start = page_size + sum((s + page_size - 1) // page_size * page_size
                                    for s in (kernel_size, ramdisk_size))
        self.assertEqual(data[dtb_start:dtb_start + len(dtb)], dtb)

    def test_prebuilt_redwood_addresses_cannot_be_overridden(self):
        self.env.update(UEFI_TARGET='redwood', FD_BASE='0x90000000')
        self.refused(self.pack(), 'prebuilt redwood BootShim has fixed addresses')

    def test_existing_redwood_prebuilt_still_packs(self):
        self.env['UEFI_TARGET'] = 'redwood'
        result = self.pack()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_bytes()[:8], b'ANDROID!')
        self.assertEqual(struct.unpack_from('<I', self.output.read_bytes(), 40)[0], 1)


class RunnerTests(unittest.TestCase):
    def test_run_refuses_probe_before_reaching_usb(self):
        result = subprocess.run(['bash', 'common/run.sh', 'lemonades'], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('XNU boot is not enabled', result.stderr)

    def test_xl_never_builds_redwood_for_lemonades(self):
        result = subprocess.run(['bash', 'xl', 'enter'], cwd=ROOT, env=dict(os.environ, DEVICE='lemonades'),
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('only redwood is supported', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
