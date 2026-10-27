#!/usr/bin/env python3
"""Boot a verified diagnostic APFS root with a verified minimal XNU in QEMU.

No physical device access. Private guest RAM mapping; no host network. Requires
the build_dynamic_root.py manifest. Its mode selects dynamic or original launchd
with one bootstrap test job. Neither is a full iOS or physical-device test.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from fetch_ios import ROOT, sha_file

spec=importlib.util.spec_from_file_location('kernel_smoke',Path(__file__).with_name('kernel-smoke.py'))
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
RAM_BASE=0x40000000
ROOT_ADDRESS=0xFC000000
RAM_SIZE=7<<30

def prepare_ram(image,output):
    size=image.stat().st_size
    if size<=0 or ROOT_ADDRESS-RAM_BASE+size+(256<<20)>RAM_SIZE:
        raise ValueError('root image does not fit guest RAM with required free space')
    with output.open('xb') as dst,image.open('rb') as src:
        dst.truncate(RAM_SIZE);dst.seek(ROOT_ADDRESS-RAM_BASE)
        shutil.copyfileobj(src,dst,8<<20)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root-manifest',type=Path,required=True)
    p.add_argument('--build-manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--timeout',type=int,default=150)
    p.add_argument('--trace-user-exceptions',action='store_true',help='enable existing kernel user exception/register tracing (systrace=1)')
    p.add_argument('--firmware',type=Path,default=Path('/opt/homebrew/share/qemu/edk2-aarch64-code.fd'))
    args=p.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'out') or out.exists(): p.error('new workspace out/ directory required')
    if not 30<=args.timeout<=600: p.error('timeout must be between 30 and 600 seconds')
    build=json.loads(args.build_manifest.read_text());root=json.loads(args.root_manifest.read_text())
    mode=root.get('mode','dynamic')
    if mode not in ('dynamic','launchd','usermanager'): p.error('unknown root mode')
    if build.get('status')!='complete' or build.get('make_exit_code')!=0: p.error('completed native build required')
    kernel=Path(build['kernel']['path']);image=Path(root['image'])
    if sha_file(kernel)!=build['kernel']['sha256']: p.error('kernel hash mismatch')
    if image.stat().st_size!=root['image_size'] or sha_file(image)!=root['image_sha256']: p.error('root image hash mismatch')
    if not args.firmware.is_file() or not shutil.which('qemu-system-aarch64'): p.error('QEMU and ARM64 EFI required')
    out.mkdir(parents=True)
    env=os.environ.copy();env.pop('LOADER_TARGET',None)
    subprocess.run(['bash','xnuloader/build.sh'],cwd=ROOT,env=env,check=True)
    shutil.copyfile(ROOT/'xnuloader/loader.efi',out/'loader.efi')
    cmdline='cpus=1 -v serial=3 loader_return_after='+str(args.timeout-15)
    if args.trace_user_exceptions: cmdline+=' systrace=1'
    subprocess.run(['python3',str(ROOT/'xnuloader/mkpayload.py'),'-o',str(out/'payload.bin'),
        'kernel='+str(kernel),'--rdres',f'{image.stat().st_size:x}','--cmdline',cmdline],check=True)
    if (out/'payload.bin').stat().st_size>ROOT_ADDRESS-0xF0000000: raise ValueError('payload overlaps root')
    serial=out/'serial.log'
    with tempfile.TemporaryDirectory(prefix='dynamic-qemu-',dir=out) as temp:
        temp=Path(temp);ram=temp/'ram.img';prepare_ram(image,ram)
        boot=temp/'boot/EFI/BOOT';boot.mkdir(parents=True)
        shutil.copyfile(out/'loader.efi',boot/'BOOTAA64.EFI')
        command=['qemu-system-aarch64','-M','virt,gic-version=3','-cpu','cortex-a76','-smp','1','-m','7G',
            '-accel','tcg','-bios',str(args.firmware),'-object',f'memory-backend-file,id=ram,size={RAM_SIZE},mem-path={ram},share=off',
            '-machine','memory-backend=ram','-drive',f'file=fat:rw:{temp / "boot"},format=raw,if=virtio',
            '-device',f'loader,file={out / "payload.bin"},addr=0xF0000000,force-raw=on',
            '-device','ramfb','-display','none','-serial',f'file:{serial}','-monitor','none','-nic','none','-no-reboot']
        with (out/'stderr.log').open('w') as error:
            proc=subprocess.Popen(command,stdout=error,stderr=error)
            try:
                deadline=time.monotonic()+args.timeout;success_at=None;observed_stable=False
                while proc.poll() is None and time.monotonic()<deadline:
                    log=serial.read_text(errors='replace') if serial.exists() else ''
                    if 'panic(cpu' in log: break
                    checked=smoke.check_log(log,mode,root.get('core_services',False),root.get('preferences',False),root.get('fsevents',False),root.get('backboard',False),root.get('locale_check',False),root.get('hid_encoding_check',False),root.get('hid_service_check',False),root.get('input_queue_check',False),root.get('touch_bridge_check',False),root.get('hid_server_restart_check',False))
                    if checked['probe_failures']: break
                    if checked['passed']:
                        if mode=='dynamic': break
                        if success_at is None: success_at=time.monotonic()
                        if time.monotonic()-success_at>=10:
                            observed_stable=True;break
                    time.sleep(.25)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill();proc.wait()
    log=serial.read_text(errors='replace') if serial.exists() else ''
    snapshots=out/'sources';snapshots.mkdir()
    sources=[Path(__file__).resolve(),ROOT/'xnuloader/loader.c',ROOT/'xnuloader/mkpayload.py',
        Path(__file__).with_name('kernel-smoke.py')]
    for source in sources: shutil.copyfile(source,snapshots/source.name)
    result=smoke.check_log(log,mode,root.get('core_services',False),root.get('preferences',False),root.get('fsevents',False),root.get('backboard',False),root.get('locale_check',False),root.get('hid_encoding_check',False),root.get('hid_service_check',False),root.get('input_queue_check',False),root.get('touch_bridge_check',False),root.get('hid_server_restart_check',False))
    if mode!='dynamic' and not observed_stable: result['passed']=False
    report={**result,'mode':mode,'simulated_integrated_touch':root.get('test_integrated_touch',False),'post_completion_observation_seconds':10 if mode!='dynamic' and observed_stable else 0,
        'scope':('QEMU APFS -> diagnostic PID1 -> Apple dyld -> libSystem; no physical 9R or Apple launchd tested' if mode=='dynamic' else ('QEMU original launchd/usermanagerd with persona initialization checks; not complete iOS or physical hardware' if mode=='usermanager' else 'QEMU original Apple launchd plus one service checking bootstrap rights; excludes other iOS jobs and physical hardware')),
        'root_manifest':str(args.root_manifest.resolve()),'root_manifest_sha256':sha_file(args.root_manifest),
        'kernel_manifest':str(args.build_manifest.resolve()),'kernel_manifest_sha256':sha_file(args.build_manifest),
        'kernel_sha256':sha_file(kernel),'image_sha256':sha_file(image),'firmware_sha256':sha_file(args.firmware),
        'artifacts_sha256':{str(path.relative_to(out)):sha_file(path) for path in [out/'loader.efi',out/'payload.bin',out/'stderr.log',*snapshots.iterdir(),*([serial] if serial.exists() else [])]},
        'cmdline':cmdline,'qemu_command':command,'expected_termination':('diagnostic PID1 exits 0 only after dynamic child exits 7, then XNU panics' if mode=='dynamic' else 'host stops observation after bootstrap checks and 10 seconds without panic; any kernel panic fails')}
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['passed','missing','unexpected_panics','probe_failures']},indent=2))
    return 0 if report['passed'] else 1

if __name__=='__main__': raise SystemExit(main())
