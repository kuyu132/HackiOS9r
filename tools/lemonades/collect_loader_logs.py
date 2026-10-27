#!/usr/bin/env python3
"""Capture logs from an ALREADY RUNNING lemonades xnuloader, without booting it.

Only getvar, oem log (RAM staging), and get_staged are sent. This does not
flash, reboot, stop a kernel, invoke adb, or write a phone storage partition.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

MAX_LOG_BYTES = 2 * 1024 * 1024
FAILURE = re.compile(r"\b(?:FAILED|FAIL|error)\b", re.I)


class CaptureError(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_getvar(output, name):
    """Accept fastboot's stdout/stderr forms; reject ambiguous or failed replies."""
    if FAILURE.search(output):
        raise CaptureError(f"getvar {name} reported failure")
    pattern = rf"^[ \t]*(?:\(bootloader\)[ \t]*)?{re.escape(name)}:[ \t]*(.*?)[ \t]*$"
    values = re.findall(pattern, output, re.M)
    if len(values) != 1:
        raise CaptureError(f"getvar {name}: expected exactly one response, got {len(values)}")
    return values[0]


def save_manifest(directory, manifest):
    tmp = directory / 'manifest.json.tmp'
    with tmp.open('w', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    tmp.replace(directory / 'manifest.json')


def capture(*, serial, output, fastboot='fastboot', count=1, interval=2.0,
            timeout=10.0, loader_image=None):
    if not serial or serial.startswith('-') or any(c.isspace() for c in serial):
        raise ValueError('a nonempty explicit USB serial is required')
    if not 1 <= count <= 1000:
        raise ValueError('count must be between 1 and 1000')
    if not math.isfinite(interval) or not 0 <= interval <= 60:
        raise ValueError('interval must be between 0 and 60 seconds')
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError('timeout must be greater than 0 and at most 60 seconds')
    executable = shutil.which(str(fastboot))
    if not executable:
        raise ValueError('fastboot executable not found')
    image_info = None
    if loader_image is not None:
        path = Path(loader_image).resolve(strict=True)
        image_info = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'matches_running_device': 'not verified; host reference only'}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        'schema': 1, 'started_at': utc_now(), 'status': 'running',
        'serial': serial, 'fastboot': str(Path(executable).resolve()),
        'collector_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'requested_snapshots': count, 'interval_seconds': interval,
        'command_timeout_seconds': timeout, 'loader_image_reference': image_info,
        'scope': 'USB session log snapshots; no flash/boot/reboot/stop/storage write',
        'physical_boot_or_ios_success_proven': False,
        'cross_reset_persistence_proven': False,
        'snapshots_are_atomic': False,
        'attempts': [],
    }
    save_manifest(output, manifest)

    def command(attempt, *args):
        entry = {'args': list(args), 'started_at': utc_now()}
        attempt['commands'].append(entry)
        save_manifest(output, manifest)
        started = time.monotonic()
        try:
            result = subprocess.run([executable, '-s', serial, *args], capture_output=True,
                                    timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            entry.update(status='timeout', stdout=(exc.stdout or b'')[:65536].decode('utf-8', 'replace'),
                         stderr=(exc.stderr or b'')[:65536].decode('utf-8', 'replace'))
            raise CaptureError(f"{' '.join(args[:2])}: timed out") from exc
        except KeyboardInterrupt:
            entry['status'] = 'interrupted'
            raise
        finally:
            entry['elapsed_seconds'] = time.monotonic() - started
        text = (result.stdout + b'\n' + result.stderr).decode('utf-8', 'replace')
        entry.update(returncode=result.returncode, stdout=result.stdout[:65536].decode('utf-8', 'replace'),
                     stderr=result.stderr[:65536].decode('utf-8', 'replace'))
        if result.returncode or FAILURE.search(text):
            entry['status'] = 'failed'
            raise CaptureError(f"{' '.join(args[:2])}: fastboot failed (exit {result.returncode})")
        entry['status'] = 'ok'
        return text

    def getvar(attempt, name):
        return parse_getvar(command(attempt, 'getvar', name), name)

    def identity(attempt):
        found = {name: getvar(attempt, name) for name in ('product', 'platform')}
        if found != {'product': 'xnuloader', 'platform': 'lemonades'}:
            raise CaptureError(f'wrong device/loader: {found}')
        return found

    exit_code = 1
    try:
        for index in range(count):
            attempt = {'index': index, 'started_at': utc_now(), 'status': 'running', 'commands': []}
            manifest['attempts'].append(attempt)
            part = output / f'{index:04d}.partial.bin'
            attempt['identity_before'] = identity(attempt)
            attempt['version'] = getvar(attempt, 'version')
            attempt['result_before'] = getvar(attempt, 'result')
            if attempt['version'] == '0.6':
                attempt['log_format'] = getvar(attempt, 'log-format')
                dropped = getvar(attempt, 'log-dropped')
                if attempt['log_format'] != 'head-tail-v1' or not re.fullmatch(r'[0-9]{1,20}', dropped):
                    raise CaptureError('invalid loader 0.6 diagnostics metadata')
                attempt['loader_dropped_before'] = int(dropped)
            command(attempt, 'oem', 'log')
            command(attempt, 'get_staged', str(part))
            if not part.is_file() or not 0 < part.stat().st_size <= MAX_LOG_BYTES:
                raise CaptureError('missing, empty, or oversized log transfer (limit 2 MiB)')
            # Check again after transfer; no partial or wrong-device capture is called complete.
            attempt['identity_after'] = identity(attempt)
            attempt['result_after'] = getvar(attempt, 'result')
            raw = part.read_bytes()
            final = output / f'{index:04d}.bin'
            part.replace(final)
            attempt.update(status='captured', finished_at=utc_now(), file=final.name,
                           bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                           result_changed=attempt['result_before'] != attempt['result_after'],
                           loader_overflow_marker=b'== LOADER LOG: middle bytes dropped;' in raw)
            # Text is a convenience view; the binary is the unmodified evidence.
            final.with_suffix('.txt').write_text(raw.decode('utf-8', 'replace'), encoding='utf-8')
            save_manifest(output, manifest)
            if index + 1 < count:
                time.sleep(interval)
        manifest['status'] = 'captured'
        exit_code = 0
    except (CaptureError, OSError) as exc:
        manifest.update(status='failed', error=str(exc))
    except KeyboardInterrupt:
        manifest.update(status='interrupted', error='interrupted by operator')
        exit_code = 130
    finally:
        for attempt in manifest['attempts']:
            if attempt['status'] == 'running':
                attempt['status'] = manifest['status']
            partial = output / f"{attempt['index']:04d}.partial.bin"
            if partial.is_file():
                size = partial.stat().st_size
                attempt['partial_file'] = partial.name
                attempt['partial_bytes'] = size
                if size <= MAX_LOG_BYTES:
                    attempt['partial_sha256'] = hashlib.sha256(partial.read_bytes()).hexdigest()
        manifest['finished_at'] = utc_now()
        manifest['captured_snapshots'] = sum(a['status'] == 'captured' for a in manifest['attempts'])
        save_manifest(output, manifest)
    return exit_code, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True, help='explicit fastboot USB serial')
    parser.add_argument('--output', required=True, type=Path, help='new host output directory')
    parser.add_argument('--fastboot', default='fastboot')
    parser.add_argument('--count', type=int, default=1, help='snapshots, 1..1000')
    parser.add_argument('--interval', type=float, default=2.0)
    parser.add_argument('--timeout', type=float, default=10.0, help='per-command timeout, at most 60s')
    parser.add_argument('--loader-image', type=Path, help='optional host image SHA-256 reference')
    args = parser.parse_args()
    try:
        code, report = capture(**vars(args))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({'status': report['status'], 'captured': report['captured_snapshots'],
                      'manifest': str(args.output.resolve() / 'manifest.json'),
                      'error': report.get('error')}, ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
