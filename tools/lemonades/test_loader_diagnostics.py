"""Run the loader's actual portable log code and composition under sanitizers."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LoaderDiagnosticsTests(unittest.TestCase):
    def test_ring_format_and_retained_panic_snapshot(self):
        source = (ROOT / 'xnuloader/loader.c').read_text()
        start = source.index('static void\ncompose_logs(')
        end = source.index('static int hc_list_is_uefis', start)
        production = '''static struct loader_log_buffer loader_log;
static char out_buf[2 * 1024 * 1024];
static const char *staged_data;
static uint64_t staged_len, completed_log_len;
''' + source[start:end]
        test = (ROOT / 'tools/lemonades/test_loader_diagnostics.c').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / 'diagnostics.c'
            c.write_text(test.replace('/* PRODUCTION_LOG_COMPOSITION */', production))
            exe = Path(tmp) / 'diagnostics'
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-I' + str(ROOT / 'xnuloader'),
                            str(c), '-o', str(exe)], check=True, capture_output=True, text=True)
            result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            self.assertIn('LOADER DIAGNOSTICS HOST PASS', result.stdout)
