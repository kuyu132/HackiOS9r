"""Reject corrupt FV headers and substituted probe/vendor sections."""
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('audit_fd', Path(__file__).with_name('audit-fd.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class FirmwareVerificationTests(unittest.TestCase):
    def header(self):
        b = bytearray(0x300000)
        struct.pack_into('<Q', b, 32, len(b))
        b[40:44] = b'_FVH'
        struct.pack_into('<H', b, 48, 56)
        struct.pack_into('<H', b, 50, (-sum(struct.unpack_from('<28H', b))) & 0xffff)
        return b

    def test_header_checksum_and_bounds(self):
        b = self.header()
        audit.check_header(b)
        b[16] ^= 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            audit.check_header(b)
        with self.assertRaises(ValueError):
            audit.check_header(b[:-1])
        struct.pack_into('<H', b, 48, 55)
        with self.assertRaisesRegex(ValueError, 'bounds'):
            audit.check_header(b)

    def fixture(self):
        modules = [{'guid': audit.PROBE_GUID, 'sections': [{'kind': 'pe32', 'size': 8, 'sha256': 'probe'}]},
                   {'guid': 'STOCK', 'sections': [{'kind': 'pe32', 'size': 16, 'sha256': 'vendor'},
                                                {'kind': 'depex', 'size': 4, 'sha256': 'dependency'}]}]
        staging = {'staged': [{'guid': 'STOCK', 'stock_name': 'Example', 'path': 'Example.inf',
                              'files': [{'sha256': 'vendor'}, {'sha256': 'dependency'}]}]}
        return modules, staging

    def test_stock_and_dependency_bytes_checked(self):
        modules, staging = self.fixture()
        self.assertEqual(len(audit.check_sections(modules, staging, 'probe')[0]), 1)
        modules[1]['sections'][1]['sha256'] = 'different'
        with self.assertRaisesRegex(ValueError, 'stock section changed'):
            audit.check_sections(modules, staging, 'probe')

    def test_missing_or_substituted_probe_rejected(self):
        modules, staging = self.fixture()
        for values, expected in [(modules[1:], 'probe'), (modules, 'another-probe')]:
            with self.assertRaisesRegex(ValueError, 'embedded probe'):
                audit.check_sections(values, staging, expected)

    def test_duplicate_guids_rejected(self):
        modules, staging = self.fixture()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            audit.check_sections(modules + modules[:1], staging, 'probe')


if __name__ == '__main__':
    unittest.main()
