import copy
import json
import struct
import unittest
from boot_contract import ROOT, VIRT_BASE, generate, parse_adt, validate_layout, node


class BootContractTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((ROOT / 'common/lemonades/boot-contract-fixture.json').read_text())
        self.stock = json.loads((ROOT / 'uefi/lemonades/stock-memory.json').read_text())

    def test_binary_contract(self):
        adt, args = generate(self.plan, self.stock)
        chosen = parse_adt(adt)['children'][b'chosen\0']['properties']
        self.assertEqual(chosen['hackios,board'], b'lemonades\0')
        self.assertEqual(chosen['psci-method'], b'smc\0')
        self.assertEqual(len(args), 736)
        self.assertEqual(struct.unpack_from('<HH', args), (2, 2))
        self.assertEqual(struct.unpack_from('<QI', args, 96), (VIRT_BASE + 0x2100000, len(adt)))
        self.assertEqual(args[40:96], bytes(56))
        self.assertTrue(args[108:].startswith(b'-v cpus=1\0'))

    def test_reject_bad_layout(self):
        mutations = [
            lambda p: p.update(target='redwood'),
            lambda p: p.update(purpose='boot'),
            lambda p: p.update(page_size=4096),
            lambda p: p.update(command_line='-v cpus=1 gpu=1'),
            lambda p: p.update(mpidr=1),
            lambda p: p.update(cntfrq=0),
            lambda p: p['ram_window'].update(address='0x9bc00000'),
            lambda p: p['ram_window'].update(address='0xffffffffffffc000'),
            lambda p: p['allocations'][0].update(size=0),
            lambda p: p['allocations'][1].update(address='0xb0400000'),
            lambda p: p['allocations'][1].update(address='0xb2400001'),
            lambda p: p['allocations'][1].update(address='0xd0000000'),
            lambda p: p['allocations'][1].update(name='kernel'),
            lambda p: p['ram_window'].update(address=True),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                plan = copy.deepcopy(self.plan)
                mutation(plan)
                with self.assertRaises(ValueError):
                    validate_layout(plan, self.stock)

    def test_reservation_in_unallocated_tail(self):
        self.stock['stock_regions'].append({'section': 'MemoryMap', 'address': 0xc0000000, 'size': 0x4000})
        with self.assertRaises(ValueError):
            generate(self.plan, self.stock)

    def test_truncated_or_malformed_tree(self):
        adt, _ = generate(self.plan, self.stock)
        for n in range(len(adt)):
            with self.assertRaises(ValueError):
                parse_adt(adt[:n])
        for broken in [adt + b'\0', b'\xff' * 8,
                       node('root', children=[node('same'), node('same')])]:
            with self.assertRaises(ValueError):
                parse_adt(broken)


if __name__ == '__main__':
    unittest.main()
