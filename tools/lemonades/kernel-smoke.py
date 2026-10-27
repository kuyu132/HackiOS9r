#!/usr/bin/env python3
"""QEMU virt XNU -> static process 1 and optional process/VM/IPC checks, using a verified kernel. No phone hardware."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / 'tools/lemonades/userland-lock.json').read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_markers(program, core_services=False, preferences=False, fsevents=False, backboard=False, locale_check=False, hid_encoding_check=False, hid_service_check=False, input_queue_check=False, touch_bridge_check=False, hid_server_restart_check=False):
    markers = ['platform qemu-virt', 'Darwin Kernel Version 22.5.0']
    if program == 'hello':
        markers += ['Hello from user space on Darwin!', 'I am process 1, uid 0, console fd 0.']
    elif program in ('dynamic','launchd','usermanager'):
        markers += ['DYN INIT v1', 'DYN PASS active-cache']
        if program!='dynamic': markers+=['DYN PASS users']
        markers+=['DYN PASS libSystem pid=', 'DYN PASS child-exit', 'DYN COMPLETE v1']
        if program!='dynamic':
            if program=='usermanager': markers+=['USERMANAGER PASS boot-task']
            markers+=['LAUNCHD HANDOFF v1','BOOTSTRAP BEGIN v1',
                            'BOOTSTRAP PASS check-in-lookup v1','AUDIT PASS sender-identity','PERSONA PASS unentitled-spawn-denied uid=501 errno=1',
                            'BOOTSTRAP PASS credentials']
            if core_services: markers+=['CORE PASS notify-cross-process']
            if program=='usermanager': markers+=['RAMFS PASS rename-swap-excl','USERMANAGER PASS manifest-kernel','USERMANAGER PASS state-files','USERMANAGER PASS system-proxy','USERMANAGER PASS muser-rpc','NSXPC PASS persona-fetch-denied','NSXPC PASS foreground-session','NSXPC PASS session-state-kernel']
            if locale_check: markers+=['LOCALE PASS iso8601']
            if input_queue_check: markers+=['INPUT QUEUE PASS select-wakeup','INPUT QUEUE PASS kernel-contract']
            if hid_encoding_check: markers+=['HID TOUCH PASS device-profile-encoding','HID TOUCH PASS event-encoding']
            if hid_service_check:
                markers+=['HID SERVICE PASS synthetic-registration','HID SERVICE PASS synthetic-delivery']
                if input_queue_check:markers+=['HID SERVICE PASS synthetic-queue-delivery']
                markers+=['HID SERVICE PASS synthetic-removal']
            if touch_bridge_check:
                markers+=['BRIDGE TEST PASS device-event-profile','BRIDGE TEST PASS daemon-delivery','BRIDGE TEST PASS restart-held-contact']
                if hid_server_restart_check:markers+=['BRIDGE TEST PASS server-restart-held-contact']
                markers+=['BRIDGE TEST PASS graceful-release-stop','BRIDGE TEST PASS synthetic-default-rejected']
            if backboard: markers+=['DESKTOP PASS hid-services']
            if fsevents: markers+=['FSEVENTS PASS file-create','FSEVENTS PASS directory-delete']
            if preferences:
                markers+=['PREFS PASS mobile-isolation']
                if fsevents: markers+=['PREFS PASS api-live-refresh','PREFS PASS external-vnode-events','PREFS PASS external-refresh']
                markers+=['PREFS PASS cross-process']
            return markers+['BOOTSTRAP COMPLETE v1']
    elif program in ('abi', 'mach'):
        if program == 'mach':
            markers += ['MACH BEGIN v1', 'MACH PASS msg2-rpc', 'MACH PASS rights-lifecycle', 'MACH PASS task-info-rpc', 'MACH COMPLETE v1']
        markers += ['ABI BEGIN v1', 'ABI PASS identity', 'ABI PASS errno', 'ABI PASS vm',
                    'ABI PASS process-ipc', 'ABI PASS cow-cleanup', 'ABI COMPLETE v1']
    else:
        raise ValueError('unknown probe: ' + program)
    return markers + ['initproc failed to start -- no exit reason available -- (signal 0, exit status 0 )']


def check_log(log, program, core_services=False, preferences=False, fsevents=False, backboard=False, locale_check=False, hid_encoding_check=False, hid_service_check=False, input_queue_check=False, touch_bridge_check=False, hid_server_restart_check=False):
    markers = expected_markers(program, core_services, preferences, fsevents, backboard, locale_check, hid_encoding_check, hid_service_check, input_queue_check, touch_bridge_check, hid_server_restart_check)
    missing = [m for m in markers if m not in log]
    panics = [line for line in log.splitlines() if line.startswith('panic(cpu')]
    unexpected = [line for line in panics if program in ('launchd','usermanager') or markers[-1] not in line]
    failures = [line for line in log.splitlines()
                if any(marker in line for marker in ('ABI FAIL:', 'BOOTSTRAP FAIL:', 'NSXPC FAIL ', 'FSEVENTS FAIL ', 'DESKTOP FAIL ', 'LOCALE FAIL ', 'HID TOUCH FAIL ', 'HID SERVICE FAIL ', 'INPUT QUEUE FAIL ', 'BRIDGE TEST FAIL '))]
    ordered = all(log.find(a) < log.find(b) for a, b in zip(markers, markers[1:]))
    job_exit_verified=True
    if program in ('launchd','usermanager'):
        begin=re.search(r'BOOTSTRAP BEGIN v1 pid=(\d+) ppid=1',log)
        job_exit_verified=False
        if begin and int(begin[1])>1:
            pid=begin[1]
            spawn=log.find('Successfully spawned bootstrap_probe['+pid+']')
            exited=re.search(r'\([^\r\n]*net\.hackios9r\.bootstrap-probe \['+pid+r'\]\)[^\r\n]*: exited due to exit\(0\)',log)
            job_exit_verified=bool(exited and 0<=spawn<begin.start()<log.find('BOOTSTRAP COMPLETE v1')<exited.start())
    preferences_daemon_verified=not preferences or bool(re.search(r'\(user/\d+/com\.apple\.cfprefsd\.xpc\.daemon \[(\d+)\]\).*Successfully spawned cfprefsd\[\1\]',log))
    fsevents_daemon_verified=not fsevents or bool(re.search(r'\(system/com\.apple\.fseventsd \[(\d+)\]\).*Successfully spawned fseventsd\[\1\]',log))
    backboard_exits=[line for line in log.splitlines() if backboard and re.search(r'\(user/\d+/com\.apple\.backboardd \[\d+\]\).*exited due to',line)]
    server_restart_verified=not hid_server_restart_check
    recovered=None
    if hid_server_restart_check:
        fault=re.search(r'BRIDGE SERVER fault server=(\d+) bridge=(\d+) probe=(\d+)',log)
        recovered=re.search(r'BRIDGE SERVER recovered server=(\d+) bridge=(\d+) service=(\d+)',log)
        if fault and recovered and fault[1]!=recovered[1] and fault[2]!=recovered[2]:
            expected=re.search(r'\(user/\d+/com\.apple\.backboardd \['+fault[1]+r'\]\).*exited due to SIGKILL \| sent by touch_bridge_probe\['+fault[3]+r'\]',log)
            old_spawn=log.find('Successfully spawned backboardd['+fault[1]+']')
            new_spawn=log.find('Successfully spawned backboardd['+recovered[1]+']')
            bridge_spawn=log.find('Successfully spawned lemonades-touch-bridge['+recovered[2]+']')
            reset_exit=re.search(r'BRIDGE EXIT pid='+fault[2]+r' status=75 frames=\d+ reset=1',log)
            server_restart_verified=bool(expected and reset_exit and
                0<=old_spawn<fault.start()<expected.start()<new_spawn<recovered.start() and
                fault.start()<reset_exit.start()<bridge_spawn<recovered.start()<log.find('BRIDGE TEST PASS server-restart-held-contact'))
            if server_restart_verified:
                backboard_exits=[line for line in backboard_exits if expected[0] not in line]
    backboard_daemon_verified=not backboard or bool(re.search(r'\(user/\d+/com\.apple\.backboardd \[(\d+)\]\).*Successfully spawned backboardd\[\1\]',log))
    bridge_lifecycle_verified=not touch_bridge_check
    if touch_bridge_check:
        initial=re.search(r'BRIDGE TEST initial pid=(\d+) service=(\d+)',log)
        restarted=re.search(r'BRIDGE TEST restarted pid=(\d+) service=(\d+)',log)
        if initial and restarted and initial[1]!=restarted[1] and initial[2]!=restarted[2]:
            first,second=initial[1],restarted[1]
            spawn1=log.find('Successfully spawned lemonades-touch-bridge['+first+']')
            spawn2=log.find('Successfully spawned lemonades-touch-bridge['+second+']')
            killed=re.search(r'\([^\r\n]*net\.hackios9r\.touch-bridge \['+first+r'\]\)[^\r\n]*: exited due to SIGKILL',log)
            final_pid=recovered[2] if hid_server_restart_check and recovered else second
            clean=re.search(r'\([^\r\n]*net\.hackios9r\.touch-bridge \['+final_pid+r'\]\)[^\r\n]*: exited due to exit\(0\)',log)
            bridge_lifecycle_verified=bool(killed and clean and
                0<=spawn1<initial.start()<killed.start()<spawn2<restarted.start()<clean.start()<log.find('BRIDGE TEST PASS graceful-release-stop') and
                'BRIDGE stopped: synthetic input rejected' in log)
    return {'passed': server_restart_verified and bridge_lifecycle_verified and not backboard_exits and backboard_daemon_verified and not missing and not unexpected and not failures and ordered and job_exit_verified and preferences_daemon_verified and fsevents_daemon_verified,
            'server_restart_verified':server_restart_verified if hid_server_restart_check else None,
            'bridge_lifecycle_verified':bridge_lifecycle_verified if touch_bridge_check else None,
            'missing': missing, 'unexpected_panics': unexpected, 'probe_failures': failures,
            'backboard_exits':backboard_exits,'backboard_daemon_verified':backboard_daemon_verified if backboard else None,
            'program': program, 'ordered': ordered,'job_exit_verified':job_exit_verified if program in ('launchd','usermanager') else None,
            'preferences_daemon_verified':preferences_daemon_verified if preferences else None,
            'fsevents_daemon_verified':fsevents_daemon_verified if fsevents else None}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--program', choices=['hello', 'abi', 'mach'], default='hello', help='static hello, BSD primitives, or Mach request/reply plus BSD primitives')
    ap.add_argument('--userland', type=Path, default=ROOT / 'out/lemonades/reference/hackios-xnu-userland')
    ap.add_argument('--firmware', type=Path, default=Path('/opt/homebrew/share/qemu/edk2-aarch64-code.fd'))
    ap.add_argument('--output', type=Path, help='retain this run in a dedicated workspace directory')
    ap.add_argument('--timeout', type=int, default=50)
    ap.add_argument('--build-manifest', type=Path, help='successful native build manifest; otherwise use pinned baseline')
    ap.add_argument('--exercise-hardware-guards', action='store_true', help='QEMU only: enable legacy phone boot-args and require process 1 to remain reachable')
    args = ap.parse_args()
    kernel = ROOT / 'prebuilt/mach.development.bcm2837'
    build = json.loads(args.build_manifest.read_text()) if args.build_manifest else None
    if build is not None:
        if build.get('status') != 'complete' or build.get('make_exit_code') != 0:
            ap.error('kernel build manifest does not report a completed build')
        kernel = Path(build['kernel']['path'])
        if not kernel.is_file() or digest(kernel) != build['kernel']['sha256']:
            ap.error('built kernel hash mismatch')
    program_src = args.userland / 'userland/src/hello.c' if args.program == 'hello' else ROOT / 'tools/lemonades/userland' / (args.program + '_probe.c')
    if not args.firmware.is_file() or not shutil.which('qemu-system-aarch64'):
        ap.error('QEMU or AArch64 EFI firmware missing')
    if not program_src.is_file():
        ap.error('missing static probe source: ' + str(program_src))
    commit = subprocess.check_output(['git', '-C', str(args.userland), 'rev-parse', 'HEAD'], text=True).strip() if args.program == 'hello' else None
    if args.program == 'hello' and (commit != LOCK['commit'] or digest(program_src) != LOCK['files_sha256']['userland/src/hello.c']):
        ap.error('userland commit/source hash mismatch')
    if build is None and digest(kernel) != LOCK['baseline_kernel_sha256']:
        ap.error('baseline kernel hash mismatch')
    if args.exercise_hardware_guards and not build:
        ap.error('guard exercise requires the new kernel build manifest')
    suffix = ('-' + args.program if args.program != 'hello' else '') + ('-guards' if args.exercise_hardware_guards else '')
    out = ROOT / 'out/lemonades' / (('kernel-smoke-built' if build else 'kernel-smoke') + suffix)
    if args.output:
        out = args.output.resolve()
        if not out.is_relative_to(ROOT / 'out'):
            ap.error('--output must be under the workspace out/ directory')
    out.mkdir(parents=True, exist_ok=True)
    serial = out / 'serial.log'
    serial.unlink(missing_ok=True)
    (out / 'result.json').unlink(missing_ok=True)
    env = os.environ.copy()
    env.pop('LOADER_TARGET', None)
    subprocess.run(['bash', 'xnuloader/build.sh'], cwd=ROOT, env=env, check=True)
    shutil.copyfile(ROOT / 'xnuloader/loader.efi', out / 'loader.efi')
    executable = out / ('hello' if args.program == 'hello' else args.program + '-probe')
    compile_cmd = ['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios16.5',
        '-Os', '-static', '-nostdlib', '-ffreestanding', '-fno-stack-protector', '-fno-builtin',
        '-Wl,-e,_start', '-Wl,-pagezero_size,0x100000000', str(program_src), '-o', str(executable)]
    if args.program == 'mach':
        sdk = ROOT / 'out/lemonades/native-deps/iPhoneOS16.5.xnu.sdk'
        if not (sdk / 'usr/include/mach/message.h').is_file():
            ap.error('prepare the pinned native SDK before the Mach probe')
        compile_cmd += ['-isysroot', str(sdk)]
    subprocess.run(compile_cmd, check=True)
    cmdline = 'cpus=1 -v serial=3 loader_return_after=20'
    if args.exercise_hardware_guards:
        cmdline += ' touchscreen=1 buttons=1 cpufreq=1 gpu=1 adreno=1 display_probe=1 wifi=1 wifi_step=1 adsp=1 speaker_probe=1'
    subprocess.run(['python3', str(ROOT / 'xnuloader/mkpayload.py'), '-o', str(out / 'payload.bin'),
        f'kernel={kernel}', f'ramdisk={executable}', '--cmdline', cmdline], check=True)
    markers = expected_markers(args.program)
    with tempfile.TemporaryDirectory(prefix='lemonades-kernel-smoke-') as temp:
        boot = Path(temp) / 'EFI/BOOT'
        boot.mkdir(parents=True)
        shutil.copyfile(out / 'loader.efi', boot / 'BOOTAA64.EFI')
        command = ['qemu-system-aarch64', '-M', 'virt,gic-version=3', '-cpu', 'cortex-a76',
            '-smp', '1', '-m', '4G', '-accel', 'tcg', '-bios', str(args.firmware),
            '-drive', f'file=fat:rw:{temp},format=raw,if=virtio', '-device',
            f'loader,file={out / "payload.bin"},addr=0xF0000000,force-raw=on', '-device', 'ramfb',
            '-display', 'none', '-serial', f'file:{serial}', '-monitor', 'none', '-nic', 'none', '-no-reboot']
        with (out / 'stderr.log').open('w') as error:
            proc = subprocess.Popen(command, stdout=error, stderr=error)
            try:
                deadline = time.monotonic() + args.timeout
                while proc.poll() is None and time.monotonic() < deadline:
                    log = serial.read_text(errors='replace') if serial.exists() else ''
                    if all(m in log for m in markers):
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
    log = serial.read_text(errors='replace') if serial.exists() else ''
    source_inputs = [program_src]
    if args.program == 'mach':
        source_inputs += [ROOT / 'tools/lemonades/userland/abi_probe.c']
        source_inputs += [sdk / 'usr/include/mach' / name for name in
                          ['message.h', 'port.h', 'task.h', 'task_info.h', 'ndr.h', 'kern_return.h']]
    snapshots = {}
    snapshot_dir = out / 'sources'
    snapshot_dir.mkdir(exist_ok=True)
    for path in source_inputs + [Path(__file__).resolve()]:
        saved = snapshot_dir / path.name
        shutil.copyfile(path, saved)
        snapshots[str(path.relative_to(ROOT))] = {'path': str(saved.relative_to(ROOT)), 'sha256': digest(saved)}
    report = {**check_log(log, args.program), 'userland_commit': commit, 'source_snapshots': snapshots,
        'scope': ('newly built minimal generic XNU with lemonades modules + static user-space probe; no physical 9R hardware or full iOS tested' if build else 'prebuilt generic XNU + freshly built loader and static user-space probe; excludes new kernel guards/touch adapter and all physical 9R hardware'),
        'build_manifest': str(args.build_manifest) if build else None,
        'legacy_hardware_args_exercised': args.exercise_hardware_guards, 'cmdline': cmdline,
        'expected_termination': 'selected static probe intentionally exits PID 1 with status 0 after required checks; XNU panics',
        'sha256': {str(p.relative_to(ROOT)): digest(p) for p in [kernel, *source_inputs, executable,
            out / 'loader.efi', out / 'payload.bin', serial]},
        'firmware_sha256': digest(args.firmware), 'compile_command': compile_cmd, 'qemu_command': command}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ['passed', 'missing', 'unexpected_panics', 'scope']}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
