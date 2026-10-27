"""Portable bridge state, with sanitizer coverage; no physical input claimed."""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
class HidTouchTests(unittest.TestCase):
    def test_transactional_touch_state_and_release(self):
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/'hid-touch-test'
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                '-I'+str(ROOT/'common/lemonades'),str(ROOT/'common/lemonades/hid_touch.c'),
                str(ROOT/'tools/lemonades/test_hid_touch.c'),'-o',str(exe)],check=True,capture_output=True,text=True)
            result=subprocess.run([str(exe)],check=True,capture_output=True,text=True)
            self.assertIn('HID TOUCH HOST PASS',result.stdout)
