import hashlib
import tempfile
from pathlib import Path
import unittest
import uuid
import protocol_audit as audit

G = '12345678-1234-5678-90AB-CDEF12345678'
PUSH = b'\x02' + uuid.UUID(G).bytes_le


class DependencyTests(unittest.TestCase):
    def test_missing_depex_is_not_true(self):
        self.assertEqual(audit.depex(None)['mode'], 'all_architectural_protocols')
        self.assertIs(audit.depex(b'\x06\x08')['expression'], True)

    def test_boolean_and_schedule_semantics(self):
        r = audit.depex(b'\x09' + PUSH + b'\x07\x05\x03\x08')
        self.assertEqual(r['mode'], 'schedule_on_request')
        self.assertEqual(r['protocols'], [G])
        self.assertEqual(r['expression'], {'and': [G, {'not': False}]})

    def test_ordering_guid_is_not_protocol(self):
        for op, mode in ((0, 'before'), (1, 'after')):
            r = audit.depex(bytes([op]) + uuid.UUID(G).bytes_le + b'\x08')
            self.assertEqual(r['mode'], mode)
            self.assertEqual(r['file_guid'], G)
            self.assertEqual(r['protocols'], [])

    def test_truncation_bad_stack_and_trailing_data(self):
        for data in (b'', b'\x02', PUSH, b'\x03\x08', b'\x05\x08', b'\x06\x06\x08',
                     b'\x06\x08\x00', b'\x06\x09\x08', b'\xff', b'\x00\x08'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                audit.depex(data)

    def test_apriori_bounds_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'raw'
            for raw in (b'bad', uuid.UUID(G).bytes_le * 2):
                path.write_bytes(raw)
                m = {'guid': audit.APRIORI, 'sections': [{'kind': 'raw', 'path': str(path),
                      'sha256': hashlib.sha256(raw).hexdigest()}]}
                with self.assertRaises(ValueError):
                    audit.apriori([m])

    def test_occurrences_never_labelled_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            def mod(name, ident, values):
                sections = []
                for kind, data in values.items():
                    path = Path(tmp) / (name + '.' + kind); path.write_bytes(data)
                    sections.append({'kind': kind, 'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()})
                return {'name': name, 'guid': ident, 'sections': sections}
            modules = [mod('order', audit.APRIORI, {'raw': uuid.UUID(G).bytes_le}),
                       mod('consumer', G, {'pe32': uuid.UUID(G).bytes_le, 'depex': PUSH + b'\x08'})]
            r = audit.analyze(modules, modules, {})
            self.assertTrue(r['drivers'][0]['depex_bypassed'])
            self.assertEqual(len(r['protocols'][0]['current_pe_occurrences']), 1)
            self.assertTrue(r['protocols'][0]['provider_status'].startswith('UNRESOLVED'))
            # Do not count watch-list constants as firmware provider evidence,
            # or schedule an EFI application as a DXE driver with empty DEPEX.
            app = mod('probe', audit.PROBE, {'pe32': uuid.UUID(G).bytes_le})
            app['file_type'] = 'Application'
            r = audit.analyze(modules + [app], modules, {})
            self.assertEqual(len(r['drivers']), 1)
            self.assertEqual(len(r['protocols'][0]['current_pe_occurrences']), 1)


if __name__ == '__main__': unittest.main()
