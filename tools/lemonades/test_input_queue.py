"""Actual portable kernel queue core and touch stream recovery under sanitizers."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2]
class InputQueueTests(unittest.TestCase):
    def test_loss_snapshot_and_poisoned_transport(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'queue-test'
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                '-I'+str(ROOT/'xnu/files/bsd'),'-I'+str(ROOT/'xnu/files/bsd/dev'),'-I'+str(ROOT/'common/lemonades'),
                str(ROOT/'tools/lemonades/test_input_queue.c'),str(ROOT/'common/lemonades/hid_touch.c'),
                str(ROOT/'common/lemonades/hid_stream.c'),'-o',str(exe)],check=True,capture_output=True,text=True)
            result=subprocess.run([str(exe)],check=True,capture_output=True,text=True)
            self.assertIn('INPUT QUEUE HOST PASS',result.stdout)
