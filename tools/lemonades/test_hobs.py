import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


trace = load('trace-hobs.py', 'hob_trace_tests')
paths = load('inspect-hob-paths.py', 'hob_path_tests')


class HobTests(unittest.TestCase):
    @staticmethod
    def te():
        data = bytearray(0x100)
        struct.pack_into('<HHBBHIIQ', data, 0, 0x5a56, 0xaa64, 1, 11, 0xf60, 0x1000, 0x1000, 0x9fc01000)
        struct.pack_into('<8sIIIIIIHHI', data, 40, b'.text', 16, 0x1000, 16, 0x1000, 0, 0, 0, 0, 0x60000020)
        data[0xc8:0xd8] = bytes(range(16))  # 0x1000 - (0xf60 - 40)
        return data

    def test_te_stripped_offset_and_preferred_base(self):
        result = trace.sections(self.te(), 'te')[0]
        self.assertEqual(result['offset'], 0xc8)
        self.assertEqual(result['address'], 0x9fc02000)
        self.assertEqual(result['data'], bytes(range(16)))
        self.assertTrue(result['executable'])

    def test_te_rejects_truncation_architecture_and_bounds(self):
        malformed = [b'', self.te()[:60]]
        for offset, fmt, value in [(0, '<H', 0), (2, '<H', 0x8664), (6, '<H', 20),
                                   (4, '<B', 0), (60, '<I', 0),
                                   (56, '<I', 0x10000), (16, '<Q', 0xfffffffffffffff0)]:
            data = self.te(); struct.pack_into(fmt, data, offset, value); malformed.append(data)
        for data in malformed:
            with self.subTest(data=data[:24]), self.assertRaises(ValueError):
                trace.sections(data, 'te')

    def refs(self, instructions, target=0x1210):
        data = struct.pack('<'+'I'*len(instructions), *instructions)
        return trace.references([{'address': 0x1000, 'data': data, 'executable': True}], {target: 'guid'})

    def test_add_uses_source_register(self):
        refs = self.refs([0x90000008, 0x91084100])  # adrp x8; add x0,x8,#0x210
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['instruction_address'], 0x1004)

    def test_unknown_and_32bit_writes_invalidate_values(self):
        for write in (0x52800008, 0xf9400128):  # mov w8,#0; ldr x8,[x9]
            self.assertEqual(self.refs([0x90000008, write, 0x91084100]), [])

    def test_calls_branches_and_data_stop_propagation(self):
        for stop in (0x94000001, 0x14000001, 0xb4000020, 0xd65f03c0, 0xffffffff):
            self.assertEqual(self.refs([0x90000008, stop, 0x91084100]), [])

    def test_shifted_add_and_register_move(self):
        self.assertEqual(len(self.refs([0x90000008, 0x91400500], 0x2000)), 1)
        self.assertEqual(len(self.refs([0x90000008, 0xaa0803e0], 0x1000)), 2)

    def test_evidence_digest_change_rejected(self):
        mapped = [{'address': 0x1000, 'data': b'12345678'}]
        reviewed = [('sample', 0x1000, 4, hashlib.sha256(b'1234').hexdigest())]
        self.assertEqual(len(paths.verify_ranges(mapped, reviewed)), 1)
        mapped[0]['data'] = b'123x5678'
        with self.assertRaises(ValueError): paths.verify_ranges(mapped, reviewed)
        with self.assertRaises(ValueError): paths.read_at(mapped, 0xfff, 1)
        with self.assertRaises(ValueError): paths.read_at(mapped, 0x1007, 2)


if __name__ == '__main__': unittest.main()
