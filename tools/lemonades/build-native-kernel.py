#!/usr/bin/env python3
"""Build the explicit minimal ARM64 research kernel on macOS; no device access.

All downloads, SDK additions, generated headers and binaries stay under out/.
No system SDK modification, no prebuilt-kernel fallback, no export-check bypass.
The existing reduced IIG shim does NOT implement user-space DriverKit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / 'tools/lemonades/native-deps-lock.json'
LOCK = json.loads(LOCK_PATH.read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def output(command, **kw):
    return subprocess.check_output(command, text=True, **kw).strip()


def run(command, log=None, allowed=(0,), **kw):
    if log is None:
        result = subprocess.run(command, **kw)
    else:
        with Path(log).open('w') as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, **kw)
    if result.returncode not in allowed:
        raise RuntimeError(f'command exited {result.returncode}: {command[0]}; log: {log}')
    return result.returncode


def fetch_repo(base, name, pin):
    path = base / name
    if not path.exists():
        run(['git', 'init', '-q', str(path)])
        command = ['git', '-C', str(path), 'fetch', '--depth', '1']
        if pin.get('sparse'):
            command += ['--filter=blob:none']
        run(command + [pin['url'], pin['commit']])
        if pin.get('sparse'):
            run(['git', '-C', str(path), 'sparse-checkout', 'set', pin['sparse']])
        run(['git', '-C', str(path), 'checkout', '-q', '--detach', pin['commit']])
    if not (path / '.git').is_dir() or output(['git', '-C', str(path), 'rev-parse', 'HEAD']) != pin['commit']:
        raise RuntimeError(f'{name}: expected pinned repository; existing files left intact')
    if output(['git', '-C', str(path), 'status', '--porcelain', '--untracked-files=no']):
        raise RuntimeError(f'{name}: modified dependency source; not overwriting')
    return path


def prepare(deps):
    deps.mkdir(parents=True, exist_ok=True)
    for name, pin in LOCK['repositories'].items():
        fetch_repo(deps, name, pin)
    archive = deps / 'MacOSX13.3.sdk.tar.xz'
    if not archive.exists():
        part = archive.with_suffix('.download')
        run(['curl', '--fail', '--location', '--retry', '2', '-o', str(part), LOCK['mac_sdk']['url']],
            deps / 'sdk-download.log')
        if sha(part) != LOCK['mac_sdk']['sha256']:
            raise RuntimeError('SDK archive digest mismatch')
        part.rename(archive)
    if sha(archive) != LOCK['mac_sdk']['sha256']:
        raise RuntimeError('SDK archive digest mismatch; refusing extraction')
    mac = deps / 'mac-sdk'
    if not (mac / LOCK['mac_sdk']['member']).is_dir():
        mac.mkdir(exist_ok=True)
        run(['tar', '-xf', str(archive), '-C', str(mac), LOCK['mac_sdk']['member']])
    sdk = deps / 'iPhoneOS16.5.xnu.sdk'
    if not sdk.exists():
        shutil.copytree(deps / 'theos-sdks/iPhoneOS16.5.sdk', sdk, symlinks=True)
    local = sdk / 'usr/local'
    for suffix in ['libexec', 'include/kernel/os', 'lib/kernel/platform']:
        (local / suffix).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(deps / 'AvailabilityVersions/availability.pl', local / 'libexec/availability.pl')
    (local / 'libexec/availability.pl').chmod(0o755)
    filtered = subprocess.run(['/usr/bin/unifdef', '-DOS_FIREHOSE_SPI=1', '-DKERNEL=1',
        str(deps / 'libdispatch/os/firehose_buffer_private.h')], capture_output=True)
    if filtered.returncode not in (0, 1):
        raise RuntimeError('firehose header filtering failed: ' + filtered.stderr.decode(errors='replace'))
    (local / 'include/kernel/os/firehose_buffer_private.h').write_bytes(filtered.stdout)
    shutil.copyfile(deps / 'libdispatch/src/firehose/firehose_types.defs',
                    local / 'include/kernel/os/firehose_types.defs')
    for name, target in [('MacOSX13.3.sdk', mac / 'MacOSX13.3.sdk'), ('iig-impl', ROOT / 'xnu-deps/iig-impl')]:
        path = deps / name
        if path.is_symlink():
            if path.resolve() != target.resolve():
                raise RuntimeError(f'unexpected dependency link: {path}')
        elif path.exists():
            raise RuntimeError(f'expected managed symlink: {path}')
        else:
            path.symlink_to(target, target_is_directory=True)
    bin_dir = deps / 'bin'
    bin_dir.mkdir(exist_ok=True)
    # Environment is supplied by this builder, avoiding shell interpolation of paths.
    iig = bin_dir / 'iig'
    iig.write_text('#!/bin/bash\nset -euo pipefail\nexport XNUDEPS="$HACKIOS_NATIVE_DEPS"\nexec "$HACKIOS_ROOT/xnu-deps/host/bin/iig" "$@"\n')
    iig.chmod(0o755)
    return sdk


def prepare_source(source):
    if not source.exists():
        run(['bash', str(ROOT / 'xnu/apply.sh'), str(source)])
    if output(['git', '-C', str(source), 'rev-parse', 'HEAD']) != LOCK['xnu_commit']:
        raise RuntimeError('unexpected XNU base revision')
    # Require the current canonical overlay; do not overwrite a developer checkout.
    run(['git', '-C', str(source), 'apply', '--reverse', '--check', str(ROOT / 'xnu/redwood.patch')])
    for path in (ROOT / 'xnu/files').rglob('*'):
        if path.is_file() and sha(path) != sha(source / path.relative_to(ROOT / 'xnu/files')):
            raise RuntimeError(f'kernel source differs from overlay: {path}')
    for path in (ROOT / 'common/lemonades').glob('s3908_*.[ch]'):
        if sha(path) != sha(source / 'bsd/dev/lemonades' / path.name):
            raise RuntimeError(f'kernel portable source differs: {path.name}')
    patch = ROOT / 'xnu/native-minimal-exports.patch'
    check = subprocess.run(['git', '-C', str(source), 'apply', '--check', str(patch)], capture_output=True)
    if check.returncode == 0:
        run(['git', '-C', str(source), 'apply', str(patch)])
    else:
        run(['git', '-C', str(source), 'apply', '--reverse', '--check', str(patch)])


def source_fingerprint(source, env):
    paths = [ROOT / p for p in ['xnu/redwood.patch', 'xnu/native-minimal-exports.patch',
        'tools/lemonades/native-clang.sh', 'tools/lemonades/build-native-kernel.py',
        'tools/lemonades/native-deps-lock.json', 'tools/lemonades/native-minimal-exports.json',
        'xnu-deps/hostinc/xnu_clang_compat.h', 'xnu-deps/host/bin/iig']]
    for folder in ['xnu/files', 'common/lemonades', 'xnu-deps/iig-impl', 'xnu-deps/build/pthread/inc']:
        paths += [p for p in (ROOT / folder).rglob('*') if p.is_file()]
    data = {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}
    data['kernel_worktree_diff'] = hashlib.sha256(subprocess.check_output(['git', '-C', str(source), 'diff', 'HEAD'])).hexdigest()
    data['compiler'] = output([env['XNU_NATIVE_CC'], '--version'])
    return data


def reuse_build(report_path, inputs):
    """Never replace evidence from an earlier build with the same input key."""
    if not report_path.exists():
        return False
    saved = json.loads(report_path.read_text())
    if saved.get('inputs') != inputs:
        raise RuntimeError('existing build input record differs; preserving it')
    if saved.get('status') == 'prepared':
        return False
    if saved.get('status') != 'complete' or saved.get('make_exit_code') != 0:
        raise RuntimeError('existing incomplete build preserved; inspect it before starting another attempt')
    kernel = saved.get('kernel', {})
    path = Path(kernel.get('path', ''))
    if not path.is_file() or sha(path) != kernel.get('sha256'):
        raise RuntimeError('completed build kernel hash mismatch; preserving evidence')
    return True


def build_libraries(source, deps, sdk, hdrs, build, env):
    cc = [str(ROOT / 'tools/lemonades/native-clang.sh'), '-arch', 'arm64', '-c', '-Os', '-mkernel',
        '-nostdinc', '-fno-builtin', '-DKERNEL=1', '-DKERNEL_PRIVATE=1', '-DPRIVATE=1',
        '-D__DARWIN_64_BIT_INO_T=1', '-DARM64_BOARD_CONFIG_BCM2837']
    inc = [f'-I{hdrs / p}' for p in ['osfmk', 'bsd', 'libkern', 'pexpert', 'iokit', 'security']]
    inc += [f'-I{source / "EXTERNAL_HEADERS"}']
    fire = ['-DXNU_KERNEL_PRIVATE=0', '-DDISPATCH_USE_DTRACE=0', '-DOS_ATOMIC_CONFIG_MEMORY_ORDER_DEPENDENCY=1',
        '-DOS_ATOMIC_CONFIG_STARVATION_FREE_ONLY=0', '-DOS_FIREHOSE_SPI=1']
    fire += [f'-I{deps / p}' for p in ['libdispatch', 'libdispatch/src', 'libdispatch/src/firehose']]
    fire += [f'-I{sdk / "usr/local/include/kernel"}', f'-I{source / "libkern/firehose"}', f'-I{hdrs / "libkern/os"}']
    run(cc + fire + inc + ['-o', str(build / 'firehose_buffer.o'), str(deps / 'libdispatch/src/firehose/firehose_buffer.c')],
        build / 'firehose.log', env=env)
    pthread = ['-fno-common', '-Wno-int-conversion', '-D__PTHREAD_EXPOSE_INTERNALS__=1',
        '-Dpthread_kern=pthread_kext_kern', '-Dcurrent_uthread=pthread_kext_current_uthread',
        f'-I{ROOT / "xnu-deps/build/pthread/inc"}']
    pthread += [f'-I{deps / p}' for p in ['libpthread', 'libpthread/include', 'libpthread/private']]
    objs = []
    for name in ['kern_init', 'kern_support', 'kern_synch']:
        obj = build / f'pthread_{name}.o'
        run(cc + pthread + inc + ['-o', str(obj), str(deps / f'libpthread/kern/{name}.c')],
            build / f'pthread-{name}.log', env=env)
        objs.append(str(obj))
    lib = sdk / 'usr/local/lib/kernel'
    run(['xcrun', 'libtool', '-static', '-o', str(lib / 'libpthread_kext.a')] + objs)
    run(['xcrun', 'libtool', '-static', '-o', str(lib / 'libfirehose_kernel.a'), str(build / 'firehose_buffer.o')])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=ROOT / 'out/lemonades/xnu-native-src')
    ap.add_argument('--deps', type=Path, default=ROOT / 'out/lemonades/native-deps')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--prepare-only', action='store_true')
    args = ap.parse_args()
    if platform.system() != 'Darwin' or not 1 <= args.jobs <= 32:
        ap.error('requires macOS and 1..32 build jobs')
    source, deps = args.source.resolve(), args.deps.resolve()
    # A single builder owns this SDK's generated libraries at a time.
    deps.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (deps / '.build.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sdk = prepare(deps)
        prepare_source(source)
        env = os.environ.copy()
        env.update(HACKIOS_NATIVE_DEPS=str(deps), HACKIOS_ROOT=str(ROOT),
            XNU_NATIVE_CC=output(['/usr/bin/xcrun', '--sdk', 'macosx', '--find', 'clang']),
            XNU_NATIVE_CXX=output(['/usr/bin/xcrun', '--sdk', 'macosx', '--find', 'clang++']))
        inputs = source_fingerprint(source, env)
        key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:16]
        build = deps / 'build' / key
        build.mkdir(parents=True, exist_ok=True)
        report_path = build / 'build.json'
        if reuse_build(report_path, inputs):
            print(f'Reusing verified completed build: {report_path}', flush=True)
            return 0
        report = {'status': 'prepared', 'profile': 'native-minimal-arm64', 'source': str(source),
            'inputs': inputs, 'sdk_metadata_version': json.loads((sdk / 'SDKSettings.json').read_text())['Version'],
            'deployment_target': '16.5', 'source_lock': LOCK, 'source_lock_sha256': sha(LOCK_PATH),
            'scope': 'generic single-core bring-up kernel with lemonades modules; reduced IIG; no Apple DART/PPL; not physical 9R validated'}
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        if args.prepare_only:
            print(report_path)
            return 0
        make = ['make', '-C', str(source), f'SDKROOT={sdk}', f'SDKROOT_RESOLVED={sdk}',
            'SDKVERSION=16.5', 'PLATFORM=iPhoneOS',
            'PLATFORMPATH=' + output(['/usr/bin/xcrun', '--sdk', 'iphoneos', '--show-sdk-platform-path']),
            'ARCH_CONFIGS=ARM64', 'MACHINE_CONFIGS=BCM2837', 'KERNEL_CONFIGS=DEVELOPMENT',
            'ARCH_STRING_FOR_CURRENT_MACHINE_CONFIG=arm64', 'BUILD_LTO=0', 'DO_CTFMERGE=0', 'BUILD_WERROR=0',
            f'IIG={deps / "bin/iig"}', f'CC={ROOT / "tools/lemonades/native-clang.sh"}',
            f'CXX={ROOT / "tools/lemonades/native-clang.sh"} --cxx', f'OBJROOT={build / "obj"}',
            f'SYMROOT={build / "sym"}', f'DSTROOT={build / "dst"}', f'-j{args.jobs}']
        report['make_command'] = make
        report['status'] = 'building'
        try:
            print('Exporting XNU headers', flush=True)
            run(make + ['exporthdrs'], build / 'exporthdrs.log', env=env)
            hdrs = build / 'obj/EXPORT_HDRS'
            if not (hdrs / 'pexpert/pexpert/hackios_platform.h').is_file():
                raise RuntimeError('platform header not exported')
            print('Compiling pinned firehose/pthread libraries', flush=True)
            build_libraries(source, deps, sdk, hdrs, build, env)
            print('Building kernel and validating all export sets', flush=True)
            with (build / 'kernel.log').open('w') as log:
                code = subprocess.run(make, stdout=log, stderr=subprocess.STDOUT, env=env).returncode
            report['make_exit_code'] = code
            if code != 0:
                raise RuntimeError(f'kernel make exited {code}; see {build / "kernel.log"}')
            kernel = build / 'obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837'
            unstripped = Path(str(kernel) + '.unstripped')
            if output(['xcrun', 'nm', '-u', str(unstripped)]):
                raise RuntimeError('undefined kernel symbols remain')
            symbols = output(['xcrun', 'nm', '-j', str(unstripped)]).splitlines()
            required = ['_lemonades_touch_frame', '_lemonades_touch_reset', '_s3908_tcm_begin', '_s3908_decode_normal',
                '_s3908_session_message', '_s3908_session_write', '_s3908_tcm_begin_message',
                '_lemonades_touch_start', '_lemonades_touch_message',
                '_s3908_geni_poll', '_s3908_transport_poll', '_lemonades_touch_bus_bind',
                '_lemonades_touch_bus_poll', '_lemonades_touch_bus_quiesced',
                '_lemonades_touch_bus_unbind', '_lemonades_touch_platform_open',
                '_lemonades_touch_platform_service', '_lemonades_touch_platform_close']
            if not set(required) <= set(symbols):
                raise RuntimeError('new touch modules are not linked')
            report.update(status='complete', required_symbols=required,
                kernel={'path': str(kernel), 'sha256': sha(kernel)},
                libraries={p.name: sha(p) for p in (sdk / 'usr/local/lib/kernel').glob('*.a')},
                export_profile_sha256=sha(ROOT / 'tools/lemonades/native-minimal-exports.json'))
        except Exception as exc:
            report.update(status='failed', error=str(exc))
            raise
        finally:
            report_path.write_text(json.dumps(report, indent=2) + '\n')
            print(f'Build manifest: {report_path}', flush=True)
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
