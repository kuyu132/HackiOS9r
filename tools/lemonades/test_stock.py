"""Offline extraction bounds, hashes, stock identity, and memory-map regressions."""
import bz2
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace as NS
import unittest

import stock_memory


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


fetch, inspect = module('fetch-stock'), module('inspect-stock')
ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'out/lemonades/stock/LE2101_14.0.0.2301'


class ExtractorTests(unittest.TestCase):
    def test_supported_compression_and_exact_length(self):
        plain = bytes(range(256)) * 32
        for kind, encoded in [(0, plain), (1, bz2.compress(plain)), (8, lzma.compress(plain))]:
            self.assertEqual(fetch.unpack_operation(kind, encoded, len(plain)), plain)
            with self.assertRaises(ValueError):
                fetch.unpack_operation(kind, encoded, len(plain) - 1)
        self.assertEqual(fetch.unpack_operation(6, b'', 4096), bytes(4096))

    def test_source_operations_and_compression_trailing_data_refused(self):
        for kind in (2, 3, 4, 5, 7, 9, 11, 12, 13, 14):
            with self.assertRaises(ValueError):
                fetch.unpack_operation(kind, b'', 0)
        for kind, data in [(1, bz2.compress(b'hello')), (8, lzma.compress(b'hello'))]:
            with self.assertRaises(ValueError):
                fetch.unpack_operation(kind, data + b'junk', 5)

    def fixture(self):
        content = b'R' * 4096 + b'9' * 4096
        data = lzma.compress(content)
        op = NS(type=8, src_extents=[], data_length=len(data), data_offset=0,
                data_sha256_hash=hashlib.sha256(data).digest(),
                dst_extents=[NS(start_block=1, num_blocks=1), NS(start_block=0, num_blocks=1)])
        result = content[4096:] + content[:4096]
        part = NS(partition_name='xbl', new_partition_info=NS(size=8192, hash=hashlib.sha256(result).digest()),
                  operations=[op], HasField=lambda key: False)
        remote = NS(at=lambda offset, size: data[offset:offset + size])
        return data, part, remote, result

    def test_noncontiguous_extents_and_hash_verified_reuse(self):
        data, part, remote, result = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            report = fetch.extract_partition(remote, 0, len(data), part, 4096, out)
            self.assertTrue(report['manifest_hash_verified'])
            self.assertEqual((out / 'xbl.img').read_bytes(), result)
            self.assertTrue(fetch.extract_partition(remote, 0, len(data), part, 4096, out)['reused'])
            (out / 'xbl.img').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'existing file differs'):
                fetch.extract_partition(remote, 0, len(data), part, 4096, out)

    def test_bad_operation_hash_never_publishes_image(self):
        data, part, remote, _ = self.fixture()
        part.operations[0].data_sha256_hash = bytes(32)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'operation SHA-256'):
                fetch.extract_partition(remote, 0, len(data), part, 4096, Path(tmp))
            self.assertFalse((Path(tmp) / 'xbl.img').exists())

    def test_final_hash_and_extent_bounds(self):
        data, part, remote, _ = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            part.new_partition_info.hash = bytes(32)
            with self.assertRaisesRegex(ValueError, 'final image SHA-256'):
                fetch.extract_partition(remote, 0, len(data), part, 4096, Path(tmp))
            part.operations[0].dst_extents[0].start_block = 2
            with self.assertRaisesRegex(ValueError, 'extent outside'):
                fetch.extract_partition(remote, 0, len(data), part, 4096, Path(tmp))

    def test_incremental_and_path_traversal_rejected(self):
        data, part, remote, _ = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            part.HasField = lambda key: True
            with self.assertRaisesRegex(ValueError, 'incremental'):
                fetch.extract_partition(remote, 0, len(data), part, 4096, Path(tmp))
            part.partition_name = '../xbl'
            with self.assertRaises(ValueError):
                fetch.extract_partition(remote, 0, len(data), part, 4096, Path(tmp))


class StockParserTests(unittest.TestCase):
    def test_fdt_rejects_short_and_out_of_bounds(self):
        for b in (b'', struct.pack('>II', 0xd00dfeed, 41) + bytes(32), bytes(40)):
            with self.assertRaises(ValueError): inspect.fdt_size(b)

    def test_boot_rejects_wrong_version_or_section_size(self):
        b = bytearray(4096)
        b[:8] = b'ANDROID!'
        struct.pack_into('<II', b, 36, 4096, 3)
        with self.assertRaises(ValueError): inspect.boot_parts(b)
        struct.pack_into('<I', b, 40, 2)
        struct.pack_into('<I', b, 1648, 1)
        with self.assertRaisesRegex(ValueError, 'outside'): inspect.boot_parts(b)

    def test_dtbo_rejects_table_outside_image(self):
        b = struct.pack('>8I', 0xd7b7ab1e, 32, 32, 32, 1, 32, 4096, 0)
        with self.assertRaises(ValueError): inspect.split_dtbo(b)

    def test_elf_rejects_table_outside_image(self):
        b = bytearray(64)
        b[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<Q', b, 32, 64)
        struct.pack_into('<HH', b, 54, 56, 1)
        with self.assertRaises(ValueError): inspect.elf_segments(b)


class MemoryTests(unittest.TestCase):
    def test_ramoops_never_becomes_heap(self):
        rows = {r['name']: r for r in stock_memory.regions(stock_memory.load())}
        self.assertEqual(rows['DXE Heap']['address'], 0x98900000)
        self.assertEqual(rows['DXE Heap']['size'], 0x3300000)
        self.assertEqual(rows['ramoops']['address'], 0xb0000000)
        self.assertEqual(rows['ramoops']['attributes'][3], 'Reserv')
        self.assertEqual(rows['UEFI FD']['address'], 0x9fc00000)
        self.assertEqual(rows['UEFI FD']['size'], 0x300000)
        self.assertNotIn('IPC SHM', rows)  # still covered by HYP, pending initialization review


@unittest.skipUnless((STOCK / 'analysis/inventory.json').exists(), 'downloaded stock fixture not present')
class RealStockTests(unittest.TestCase):
    def test_download_metadata_pin(self):
        pin = json.loads(Path(__file__).with_name('firmware-sources.json').read_text())
        header = (STOCK / 'payload-metadata.bin').read_bytes()
        manifest_size = struct.unpack_from('>Q', header, 12)[0]
        self.assertEqual(fetch.sha(header[:24 + manifest_size]), pin['properties_metadata_sha256'])
        self.assertEqual(fetch.URL, pin['download_url'])

    def test_all_images_match_payload_manifest(self):
        report = json.loads((STOCK / 'extraction.json').read_text())
        self.assertEqual(len(report['extracted']), 16)
        for p in report['extracted']:
            self.assertEqual(fetch.sha((STOCK / (p['name'] + '.img')).read_bytes()), p['sha256'])

    def test_profile_matches_both_stock_variants(self):
        report = json.loads((STOCK / 'analysis/inventory.json').read_text())
        profile = stock_memory.load()
        for name in ('xbl', 'xbl_lp5'):
            self.assertEqual(report['xbl'][name]['memory_map'], profile['stock_regions'])
            self.assertEqual(report['xbl'][name]['uefiplat_sha256'], profile['uefiplat_sha256'])

    def test_stock_boot_and_dtbo_counts_and_target_selection(self):
        report = json.loads((STOCK / 'analysis/inventory.json').read_text())
        self.assertEqual(len(report['boot']['boot']['trees']), 22)
        self.assertEqual(len(report['dtbo']), 19)
        matching = [d for d in report['dtbo'] if d['oplus,dtsi_no'] == [20828]]
        self.assertEqual([d['index'] for d in matching], [17])
        self.assertEqual(report['boot']['boot']['dtb_addr'], 0x1f00000)

    def test_staged_variants_use_only_their_stock_aarch64_binaries(self):
        for folder, variant in [('uefi-stock-overlay', 'xbl'), ('uefi-stock-lp5-overlay', 'xbl_lp5')]:
            root = ROOT / 'out/lemonades' / folder
            if not (root / 'stock-staging.json').exists():
                self.skipTest('staged overlays not present')
            report = json.loads((root / 'stock-staging.json').read_text())
            self.assertEqual(report['variant'], variant)
            self.assertEqual(len(report['staged']), 73)
            self.assertFalse((root / 'Resources/DTBs/lemonades.dtb').exists())
            count = 0
            for item in report['staged']:
                for binary in item.get('files', []):
                    path = (root / item['path']).parent / binary['file']
                    b = path.read_bytes()
                    self.assertEqual(fetch.sha(b), binary['sha256'])
                    self.assertIn('/analysis/' + variant + '/modules/', binary['source_section'])
                    self.assertEqual(b, Path(binary['source_section']).read_bytes())
                    if path.suffix == '.efi':
                        offset = struct.unpack_from('<I', b, 60)[0] if b[:2] == b'MZ' else 0
                        self.assertEqual(b[offset:offset + 4], b'PE\0\0')
                        self.assertEqual(struct.unpack_from('<H', b, offset + 4)[0], 0xaa64)
                        count += 1
            self.assertEqual(count, 51)


if __name__ == '__main__':
    unittest.main(verbosity=2)
