#!/usr/bin/env python3
"""Boot the 9R probe EFI under QEMU: tests EFI execution, not 9R hardware support."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--firmware', type=Path, default=Path('/opt/homebrew/share/qemu/edk2-aarch64-code.fd'))
    ap.add_argument('--loader', type=Path, default=ROOT / 'out/lemonades/loader.efi')
    ap.add_argument('--timeout', type=int, default=40)
    args = ap.parse_args()
    if not args.firmware.is_file() or not args.loader.is_file():
        ap.error('firmware or probe loader missing')
    output = ROOT / 'out/lemonades'
    output.mkdir(parents=True, exist_ok=True)
    serial = output / 'qemu-probe.log'
    serial.unlink(missing_ok=True)  # Never accept a previous run before QEMU opens its serial file.
    markers = ['platform lemonades', 'LEMONADES PROBE: UEFI diagnostics only',
               'LEMONADES protocol snapshot: presence only, not hardware readiness',
               'memory map (type 7 = free', 'LEMONADES PROBE: USB protocol unavailable; returning to UEFI']
    with tempfile.TemporaryDirectory(prefix='lemonades-efi-') as tmp:
        boot = Path(tmp) / 'EFI/BOOT'
        boot.mkdir(parents=True)
        shutil.copyfile(args.loader, boot / 'BOOTAA64.EFI')
        cmd = ['qemu-system-aarch64', '-machine', 'virt', '-cpu', 'cortex-a72', '-accel', 'tcg',
               '-m', '512', '-bios', str(args.firmware), '-device', 'ramfb', '-display', 'none',
               '-nic', 'none', '-monitor', 'none', '-serial', f'file:{serial}',
               '-drive', f'format=raw,file=fat:rw:{tmp}']
        with (output / 'qemu-stderr.log').open('w') as err:
            proc = subprocess.Popen(cmd, stdout=err, stderr=err)
            text = ''
            try:
                deadline = time.monotonic() + args.timeout
                while time.monotonic() < deadline and proc.poll() is None:
                    text = serial.read_text(errors='replace') if serial.exists() else ''
                    if all(m in text for m in markers):
                        break
                    time.sleep(0.25)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
    missing = [m for m in markers if m not in text]
    report = {'passed': not missing, 'missing': missing,
              'protocol_status_lines': sum(line.startswith('protocol ') for line in text.splitlines()),
              'loader_sha256': hashlib.sha256(args.loader.read_bytes()).hexdigest(),
              'scope': 'QEMU EFI execution only; no physical 9R or Qualcomm USB tested',
              'serial_log': str(serial)}
    (output / 'qemu-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(missing))


if __name__ == '__main__':
    main()
