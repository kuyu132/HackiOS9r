"""Use a real subprocess fixture, never a connected phone or real fastboot."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from collect_loader_logs import capture, CaptureError, parse_getvar


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.fake = self.base / 'fastboot'
        self.fake.write_text(f'#!{sys.executable}\n' + '''
import json, sys, time
from pathlib import Path
root = Path(__file__).parent
cfg = json.loads((root/'config.json').read_text())
args = sys.argv[1:]
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps(args)+'\\n')
assert args[:2] == ['-s', 'TEST-SERIAL']
cmd = args[2:]
if cmd[0] == 'getvar':
    name = cmd[1]
    value = {'product':'xnuloader', 'platform':'lemonades', 'version':'0.6', 'result':'idle',
             'log-format':'head-tail-v1', 'log-dropped':'0'}[name]
    if name == 'platform' and cfg.get('wrong'): value = 'redwood'
    if name == 'platform' and cfg.get('switch') and (root/'transfers').exists(): value = 'other'
    print('(bootloader) '+name+': '+value, file=sys.stderr)
elif cmd == ['oem', 'log']:
    if cfg.get('fail_oem'):
        print('FAILED (remote: unknown command)', file=sys.stderr); sys.exit(0)
    print('OKAY', file=sys.stderr)
elif cmd[0] == 'get_staged':
    p = Path(cmd[1])
    counter = root/'transfers'
    n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n+1))
    raw = b'boot\\x00\\xff\\npanic: simulated\\n'
    if cfg.get('oversize'): raw = b'x' * (2*1024*1024+1)
    if cfg.get('empty'): raw = b''
    p.write_bytes(raw)
    if cfg.get('timeout'): time.sleep(10)
    if cfg.get('fail_second') and n == 1:
        print('FAILED (USB disconnected)', file=sys.stderr); sys.exit(1)
else:
    raise AssertionError('unapproved command: '+str(cmd))
''')
        self.fake.chmod(0o755)

    def run_capture(self, cfg=None, **kwargs):
        (self.base / 'config.json').write_text(json.dumps(cfg or {}))
        return capture(serial='TEST-SERIAL', output=self.base / 'capture',
                       fastboot=str(self.fake), interval=0, **kwargs)

    def calls(self):
        return [json.loads(line)[2:] for line in (self.base / 'calls.jsonl').read_text().splitlines()]

    def test_raw_evidence_hash_and_only_read_commands(self):
        code, report = self.run_capture(count=2)
        self.assertEqual(code, 0)
        self.assertEqual(report['captured_snapshots'], 2)
        self.assertFalse(report['physical_boot_or_ios_success_proven'])
        raw = (self.base / 'capture/0000.bin').read_bytes()
        self.assertEqual(raw, b'boot\x00\xff\npanic: simulated\n')
        self.assertEqual(report['attempts'][0]['sha256'], hashlib.sha256(raw).hexdigest())
        for cmd in self.calls():
            self.assertTrue(cmd[0] == 'getvar' or cmd == ['oem', 'log'] or cmd[0] == 'get_staged')
        self.assertEqual(json.loads((self.base / 'capture/manifest.json').read_text()), report)

    def test_wrong_platform_never_stages_or_uploads(self):
        code, report = self.run_capture({'wrong': True})
        self.assertEqual(code, 1)
        self.assertEqual(report['captured_snapshots'], 0)
        self.assertTrue(all(c[0] == 'getvar' for c in self.calls()))

    def test_zero_exit_failed_command_is_failure(self):
        code, report = self.run_capture({'fail_oem': True})
        self.assertEqual(code, 1)
        self.assertEqual(report['captured_snapshots'], 0)
        self.assertNotIn('get_staged', [c[0] for c in self.calls()])

    def test_timeout_preserves_partial_and_reports_failure(self):
        code, report = self.run_capture({'timeout': True}, timeout=0.5)
        self.assertEqual(code, 1)
        self.assertIn('timed out', report['error'])
        self.assertTrue((self.base / 'capture/0000.partial.bin').exists())
        self.assertFalse((self.base / 'capture/0000.bin').exists())

    def test_disconnect_preserves_prior_snapshot(self):
        code, report = self.run_capture({'fail_second': True}, count=3)
        self.assertEqual(code, 1)
        self.assertEqual(report['captured_snapshots'], 1)
        self.assertTrue((self.base / 'capture/0000.bin').exists())
        self.assertTrue((self.base / 'capture/0001.partial.bin').exists())
        self.assertEqual(len(report['attempts']), 2)

    def test_device_change_does_not_validate_transferred_file(self):
        code, report = self.run_capture({'switch': True})
        self.assertEqual(code, 1)
        self.assertEqual(report['captured_snapshots'], 0)
        self.assertTrue((self.base / 'capture/0000.partial.bin').exists())

    def test_oversized_transfer_is_not_accepted(self):
        code, report = self.run_capture({'oversize': True})
        self.assertEqual(code, 1)
        self.assertEqual(report['captured_snapshots'], 0)
        self.assertIn('oversized', report['error'])

    def test_empty_transfer_is_not_accepted(self):
        code, report = self.run_capture({'empty': True})
        self.assertEqual(code, 1)
        self.assertEqual(report['captured_snapshots'], 0)

    def test_existing_directory_and_invalid_limits_send_no_commands(self):
        for kwargs in ({'count': 0}, {'count': 1001}, {'timeout': float('nan')},
                       {'timeout': 61}, {'interval': float('inf')}, {'serial': '-bad'}):
            opts = dict(serial='TEST-SERIAL', output=self.base / 'capture', fastboot=str(self.fake))
            opts.update(kwargs)
            with self.assertRaises(ValueError): capture(**opts)
        (self.base / 'capture').mkdir()
        with self.assertRaises(FileExistsError): self.run_capture()
        self.assertFalse((self.base / 'calls.jsonl').exists())

    def test_interruption_leaves_manifest(self):
        (self.base / 'config.json').write_text('{}')
        with patch('collect_loader_logs.subprocess.run', side_effect=KeyboardInterrupt):
            code, report = self.run_capture()
        self.assertEqual(code, 130)
        self.assertEqual(report['status'], 'interrupted')
        self.assertTrue((self.base / 'capture/manifest.json').exists())

    def test_getvar_parser_rejects_missing_duplicate_conflicting_and_failed(self):
        self.assertEqual(parse_getvar('product: xnuloader\nFinished. Total time: 0.01s', 'product'), 'xnuloader')
        self.assertEqual(parse_getvar('unknown: \nFinished. Total time: 0.01s', 'unknown'), '')
        for text in ('', 'product: xnuloader\nproduct: xnuloader',
                     'product: xnuloader\nproduct: other', 'product: xnuloader\nFAILED',
                     'notproduct: xnuloader'):
            with self.assertRaises(CaptureError): parse_getvar(text, 'product')
