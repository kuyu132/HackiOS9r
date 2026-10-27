#!/usr/bin/env python3
"""Build an isolated APFS root for Apple dyld/libSystem integration, not full iOS.

Reads verified extraction manifests. Preserves Apple binaries; stages a separately
compiled diagnostic PID1 at /sbin/launchd, with Apple's launchd stored as .apple.
Never modifies extraction inputs or a pre-existing output directory.
"""
import argparse
import json
import plistlib
from pathlib import Path
import shutil
import stat
import subprocess
from fetch_ios import ROOT, LOCK as IOS_LOCK, LOCK_PATH, sha_file

LOCK=json.loads((Path(__file__).with_name('dynamic-userland-lock.json')).read_text())
CACHE='System/Library/Caches/com.apple.dyld'

def verified_entry(tree,manifest,name):
    path=tree/name;entry=manifest['entries'][name]
    if entry.get('type')!='file' or path.is_symlink() or not path.is_file() or sha_file(path)!=entry['sha256']:
        raise ValueError('extracted input mismatch: '+name)
    if 'source_uid' not in entry or 'source_gid' not in entry: raise ValueError('missing source ownership: '+name)
    return path,entry

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['dynamic','launchd','usermanager'],default='dynamic',help='launchd runs a bootstrap test; usermanager also imports the original persona provider')
    p.add_argument('--provider',type=Path,default=ROOT/'out/lemonades/ios165-source/usermanager-provider')
    p.add_argument('--core-services',type=Path,help='verified rootfs extraction of original logd and notifyd jobs/binaries')
    p.add_argument('--log-helper',type=Path,help='verified rootfs extraction of original logd_helper job/binary; requires --core-services')
    p.add_argument('--preferences',type=Path,help='verified rootfs extraction of original cfprefsd and its two jobs; requires usermanager mode')
    p.add_argument('--fsevents',type=Path,help='verified rootfs extraction of original fseventsd and job; requires --preferences')
    p.add_argument('--backboard',type=Path,help='verified desktop-provider extraction; imports original backboardd, requires all base services')
    p.add_argument('--backboard-config',type=Path,help='verified original BackBoard event processor configuration; requires --backboard')
    p.add_argument('--containers',type=Path,help='verified original container providers and jobs; requires --backboard')
    p.add_argument('--icu',type=Path,help='verified original ICU data extraction; also enables locale preflight')
    p.add_argument('--check-locale',action='store_true',help='run locale/ISO8601 preflight without adding data, for controlled comparisons')
    p.add_argument('--check-hid-server-restart',action='store_true',help='fault-inject original HID server in isolated QEMU root; requires --check-touch-bridge')
    p.add_argument('--test-integrated-touch',action='store_true',help='explicit simulated built-in touch identity in isolated test root; requires --check-touch-bridge, not physical readiness')
    p.add_argument('--touch-bridge',action='store_true',help='install launchd-owned snapshot-to-HID bridge; requires --backboard')
    p.add_argument('--check-touch-bridge',action='store_true',help='isolated synthetic crash/restart/stop test; requires --touch-bridge')
    p.add_argument('--check-input-queue',action='store_true',help='test exclusive snapshot input node, recovery and synthetic queue-to-HID path; requires new kernel')
    p.add_argument('--hid-service-permissions',action='store_true',help='ad-hoc sign only synthetic HID probe with dispatch/monitor declarations; research kernel only, requires --check-hid-service')
    p.add_argument('--check-hid-service',action='store_true',help='run isolated synthetic HID registration/delivery/removal diagnostic; requires --backboard')
    p.add_argument('--check-hid-encoding',action='store_true',help='validate synthetic touch record encoding with original IOKit; no devices or events published')
    p.add_argument('--rootfs',type=Path,default=ROOT/'out/lemonades/ios165-source/rootfs-core')
    p.add_argument('--cache',type=Path,default=ROOT/'out/lemonades/ios165-source/os-cache-owned')
    args=p.parse_args();out=args.output.resolve()
    args.rootfs=args.rootfs.resolve();args.cache=args.cache.resolve()
    if not out.is_relative_to(ROOT/'out') or out.exists(): p.error('a new directory under workspace out/ is required')
    reference=ROOT/'out/lemonades/reference/hackios-xnu-userland'
    commit=subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip()
    if commit!=LOCK['commit']: p.error('reference commit mismatch')
    for path,digest in LOCK['files_sha256'].items():
        if sha_file(reference/path)!=digest: p.error('reference source changed: '+path)
    sdk=ROOT/'out/lemonades/native-deps/iPhoneOS16.5.xnu.sdk'
    if not sdk.is_dir(): p.error('pinned native SDK required')
    source=ROOT/'tools/lemonades/userland'
    inputs={};manifest_lines=[]
    root_manifest=json.loads(args.rootfs.with_name(args.rootfs.name+'-extraction.json').read_text())
    cache_manifest=json.loads(args.cache.with_name(args.cache.name+'-extraction.json').read_text())
    provider_manifest=None
    core_manifest=None
    helper_manifest=None
    preferences_manifest=None
    fsevents_manifest=None
    backboard_manifest=None
    backboard_config_manifest=None
    containers_manifest=None
    icu_manifest=None
    if args.mode=='usermanager':
        args.provider=args.provider.resolve()
        provider_manifest=json.loads(args.provider.with_name(args.provider.name+'-extraction.json').read_text())
        if provider_manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or provider_manifest.get('component')!=IOS_LOCK['components']['rootfs']:
            p.error('provider extraction does not match pinned rootfs')
    if args.core_services:
        if args.mode!='usermanager': p.error('--core-services requires usermanager mode')
        args.core_services=args.core_services.resolve()
        core_manifest=json.loads(args.core_services.with_name(args.core_services.name+'-extraction.json').read_text())
        if core_manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or core_manifest.get('component')!=IOS_LOCK['components']['rootfs']:
            p.error('core services extraction does not match pinned rootfs')
    if args.log_helper:
        if not core_manifest: p.error('--log-helper requires --core-services')
        args.log_helper=args.log_helper.resolve()
        helper_manifest=json.loads(args.log_helper.with_name(args.log_helper.name+'-extraction.json').read_text())
        if helper_manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or helper_manifest.get('component')!=IOS_LOCK['components']['rootfs']:
            p.error('log helper extraction does not match pinned rootfs')
    if args.preferences:
        if args.mode!='usermanager': p.error('--preferences requires usermanager mode')
        args.preferences=args.preferences.resolve()
        preferences_manifest=json.loads(args.preferences.with_name(args.preferences.name+'-extraction.json').read_text())
        if preferences_manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or preferences_manifest.get('component')!=IOS_LOCK['components']['rootfs']:
            p.error('preferences extraction does not match pinned rootfs')
    if args.fsevents:
        if not preferences_manifest: p.error('--fsevents requires --preferences')
        args.fsevents=args.fsevents.resolve()
        fsevents_manifest=json.loads(args.fsevents.with_name(args.fsevents.name+'-extraction.json').read_text())
        if fsevents_manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or fsevents_manifest.get('component')!=IOS_LOCK['components']['rootfs']:
            p.error('fsevents extraction does not match pinned rootfs')
    if args.backboard:
        if not all([core_manifest,helper_manifest,preferences_manifest,fsevents_manifest]):
            p.error('--backboard requires core services, log helper, preferences and fsevents')
        args.backboard=args.backboard.resolve()
        backboard_manifest=json.loads(args.backboard.with_name(args.backboard.name+'-extraction.json').read_text())
        if backboard_manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or backboard_manifest.get('component')!=IOS_LOCK['components']['rootfs']:
            p.error('backboard extraction does not match pinned rootfs')
    if args.backboard_config:
        if not backboard_manifest:p.error('--backboard-config requires --backboard')
        args.backboard_config=args.backboard_config.resolve()
        backboard_config_manifest=json.loads(args.backboard_config.with_name(args.backboard_config.name+'-extraction.json').read_text())
        if backboard_config_manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or backboard_config_manifest.get('component')!=IOS_LOCK['components']['rootfs']:
            p.error('BackBoard configuration extraction does not match pinned rootfs')
    if args.containers:
        if not backboard_manifest:p.error('--containers requires --backboard')
        args.containers=args.containers.resolve()
        containers_manifest=json.loads(args.containers.with_name(args.containers.name+'-extraction.json').read_text())
        if containers_manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or containers_manifest.get('component')!=IOS_LOCK['components']['rootfs']:
            p.error('container extraction does not match pinned rootfs')
    if args.icu:
        args.icu=args.icu.resolve()
        icu_manifest=json.loads(args.icu.with_name(args.icu.name+'-extraction.json').read_text())
        if icu_manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or icu_manifest.get('component')!=IOS_LOCK['components']['rootfs']:
            p.error('ICU extraction does not match pinned rootfs')
    locale_check=bool(icu_manifest or args.check_locale)
    if locale_check and args.mode=='dynamic':p.error('locale preflight requires launchd or usermanager mode')
    if args.check_hid_encoding and args.mode=='dynamic':p.error('HID encoding check requires launchd or usermanager mode')
    if args.check_input_queue and args.mode=='dynamic':p.error('input queue check requires launchd or usermanager mode')
    if args.hid_service_permissions and not args.check_hid_service:p.error('--hid-service-permissions requires --check-hid-service')
    if args.check_hid_service and not backboard_manifest:p.error('HID service check requires --backboard')
    if args.test_integrated_touch and not args.check_touch_bridge:p.error('--test-integrated-touch requires --check-touch-bridge')
    if args.check_hid_server_restart and not args.check_touch_bridge:p.error('--check-hid-server-restart requires --check-touch-bridge')
    if args.touch_bridge and not backboard_manifest:p.error('--touch-bridge requires --backboard')
    if args.check_touch_bridge and not args.touch_bridge:p.error('--check-touch-bridge requires --touch-bridge')
    if args.touch_bridge and (args.check_input_queue or args.check_hid_service):p.error('bridge and exclusive input/HID probes require separate roots')
    for manifest,component in [(root_manifest,'rootfs'),(cache_manifest,'os-cryptex')]:
        if manifest.get('source_lock_sha256')!=sha_file(LOCK_PATH) or manifest.get('component')!=IOS_LOCK['components'][component]:
            p.error('extraction does not match pinned iOS component: '+component)
    out.mkdir(parents=True);tree=out/'root'
    for name in ['sbin','bin','usr/lib','dev','private/var','private/tmp','System/Library/CoreServices']:
        (tree/name).mkdir(parents=True,exist_ok=True)
    (tree/'var').symlink_to('private/var');(tree/'tmp').symlink_to('private/var/tmp')
    def stage(source_tree,manifest,name,destination):
        path,entry=verified_entry(source_tree,manifest,name)
        target=tree/destination;target.parent.mkdir(parents=True,exist_ok=True)
        # Copy rather than link: later experiments cannot mutate verified inputs.
        shutil.copy2(path,target)
        inputs[str(path.relative_to(ROOT))]=entry['sha256']
        manifest_lines.append(f'{stat.S_IFREG|entry["mode"]:o}\t{entry["source_uid"]}\t{entry["source_gid"]}\t{destination}\n')
    for name,destination in [('usr/lib/dyld','usr/lib/dyld'),('sbin/launchd','sbin/launchd.apple'),
        ('System/Library/CoreServices/SystemVersion.plist','System/Library/CoreServices/SystemVersion.plist')]:
        stage(args.rootfs,root_manifest,name,destination)
    if args.mode!='dynamic':
        for name in ['usr/libexec/xpcproxy','private/etc/passwd','private/etc/group','private/etc/master.passwd']:
            stage(args.rootfs,root_manifest,name,name)
        (tree/'etc').symlink_to('private/etc')
        jobs=tree/'System/Library/LaunchDaemons';jobs.mkdir(parents=True)
        job={'Label':'net.hackios9r.bootstrap-probe','ProgramArguments':['/bin/bootstrap_probe'],
             'RunAtLoad':True,'KeepAlive':False,'UserName':'root',
             'MachServices':{'net.hackios9r.bootstrap-probe':True},
             'StandardOutPath':'/dev/console','StandardErrorPath':'/dev/console'}
        (jobs/'net.hackios9r.bootstrap-probe.plist').write_bytes(plistlib.dumps(job))
        if args.touch_bridge:
            bridge_job={'Label':'net.hackios9r.touch-bridge','ProgramArguments':['/usr/libexec/lemonades-touch-bridge'],
                'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':3,'ExitTimeOut':5,
                'UserName':'root','StandardOutPath':'/dev/console','StandardErrorPath':'/dev/console'}
            if args.check_touch_bridge:bridge_job['ProgramArguments'].append('--allow-synthetic')
            if args.test_integrated_touch:bridge_job['ProgramArguments'].append('--test-integrated')
            (jobs/'net.hackios9r.touch-bridge.plist').write_bytes(plistlib.dumps(bridge_job))
        if provider_manifest:
            for name in ['usr/libexec/usermanagerd','System/Library/LaunchDaemons/com.apple.mobile.usermanagerd.plist']:
                stage(args.provider,provider_manifest,name,name)
            job_path=jobs/'com.apple.mobile.usermanagerd.plist'
            original_job=plistlib.loads(job_path.read_bytes())
            # Only route diagnostics; retain the original launch/entitlement policy.
            original_job.update(StandardOutPath='/dev/console',StandardErrorPath='/dev/console')
            original_job.setdefault('EnvironmentVariables',{})['OS_ACTIVITY_DT_MODE']='YES'
            job_path.write_bytes(plistlib.dumps(original_job))
        if core_manifest:
            for name in ['usr/libexec/logd','usr/sbin/notifyd',
                         'System/Library/LaunchDaemons/com.apple.logd.plist',
                         'System/Library/LaunchDaemons/com.apple.notifyd.plist']:
                stage(args.core_services,core_manifest,name,name)
            for name in ['com.apple.logd.plist','com.apple.notifyd.plist']:
                path=jobs/name;job=plistlib.loads(path.read_bytes())
                job.update(StandardOutPath='/dev/console',StandardErrorPath='/dev/console')
                job.setdefault('EnvironmentVariables',{})['OS_ACTIVITY_DT_MODE']='YES'
                if name=='com.apple.logd.plist':
                    job.update(StandardOutPath='/private/var/db/diagnostics/bringup.log',
                               StandardErrorPath='/private/var/db/diagnostics/bringup.log')
                path.write_bytes(plistlib.dumps(job))
        if helper_manifest:
            for name in ['usr/libexec/logd_helper','System/Library/LaunchDaemons/com.apple.logd_helper.plist']:
                stage(args.log_helper,helper_manifest,name,name)
            path=jobs/'com.apple.logd_helper.plist';job=plistlib.loads(path.read_bytes())
            job.update(StandardOutPath='/dev/console',StandardErrorPath='/dev/console')
            job.setdefault('EnvironmentVariables',{})['OS_ACTIVITY_DT_MODE']='YES'
            path.write_bytes(plistlib.dumps(job))
        if preferences_manifest:
            stage(args.preferences,preferences_manifest,'usr/sbin/cfprefsd','usr/sbin/cfprefsd')
            for name in ['com.apple.cfprefsd.xpc.daemon.plist','com.apple.cfprefsd.xpc.daemon.system.plist']:
                path='System/Library/LaunchDaemons/'+name
                stage(args.preferences,preferences_manifest,path,path)
                target=tree/path;job=plistlib.loads(target.read_bytes())
                # Preserve feature-flag Disabled and session/domain configuration.
                job.update(StandardOutPath='/dev/console',StandardErrorPath='/dev/console')
                job.setdefault('EnvironmentVariables',{})['OS_ACTIVITY_DT_MODE']='YES'
                target.write_bytes(plistlib.dumps(job))
        if fsevents_manifest:
            for name in ['usr/libexec/fseventsd','System/Library/LaunchDaemons/com.apple.fseventsd.plist']:
                stage(args.fsevents,fsevents_manifest,name,name)
            path=jobs/'com.apple.fseventsd.plist';job=plistlib.loads(path.read_bytes())
            job.update(StandardOutPath='/dev/console',StandardErrorPath='/dev/console')
            job.setdefault('EnvironmentVariables',{})['OS_ACTIVITY_DT_MODE']='YES'
            path.write_bytes(plistlib.dumps(job))
        if backboard_manifest:
            for name in ['usr/libexec/backboardd','System/Library/LaunchDaemons/com.apple.backboardd.plist']:
                stage(args.backboard,backboard_manifest,name,name)
            path=jobs/'com.apple.backboardd.plist';job=plistlib.loads(path.read_bytes())
            job.update(StandardOutPath='/private/var/mobile/Library/Logs/backboard-bringup.log',
                       StandardErrorPath='/private/var/mobile/Library/Logs/backboard-bringup.log')
            job.setdefault('EnvironmentVariables',{})['OS_ACTIVITY_DT_MODE']='YES'
            path.write_bytes(plistlib.dumps(job))
        if backboard_config_manifest:
            name='System/Library/BackBoard/EventProcessorConfiguration.plist'
            stage(args.backboard_config,backboard_config_manifest,name,name)
        if containers_manifest:
            for name in ['usr/libexec/containermanagerd','usr/libexec/containermanagerd_system',
                         'System/Library/LaunchDaemons/com.apple.containermanagerd.plist',
                         'System/Library/LaunchDaemons/com.apple.containermanagerd.system.plist']:
                stage(args.containers,containers_manifest,name,name)
            for name in ['com.apple.containermanagerd.plist','com.apple.containermanagerd.system.plist']:
                path=jobs/name;job=plistlib.loads(path.read_bytes())
                job.update(StandardOutPath='/dev/console',StandardErrorPath='/dev/console')
                job.setdefault('EnvironmentVariables',{})['OS_ACTIVITY_DT_MODE']='YES'
                path.write_bytes(plistlib.dumps(job))
    if icu_manifest:
        for name in ['usr/share/icu/icudt70l.dat','usr/share/icu/icutzformat.txt']:
            stage(args.icu,icu_manifest,name,name)
    names=sorted(n for n in cache_manifest['entries'] if n.startswith(CACHE+'/dyld_shared_cache_arm64') and not n.endswith('.symbols'))
    if len(names)!=43 or CACHE+'/dyld_shared_cache_arm64' not in names: raise ValueError('unexpected runtime cache set')
    for name in names: stage(args.cache,cache_manifest,name,'System/Cryptexes/OS/'+name)
    with (args.cache/CACHE/'dyld_shared_cache_arm64').open('rb') as cache:
        if cache.read(16)!=b'dyld_v1   arm64\0': raise ValueError('shared cache is not arm64')
    cc=['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios16.5','-isysroot',str(sdk)]
    static=cc+['-Os','-static','-nostdlib','-ffreestanding','-fno-stack-protector','-fno-builtin',
               '-Wl,-e,_start','-Wl,-pagezero_size,0x100000000',str(source/'dynamic_init.c'),'-o',str(tree/'sbin/launchd')]
    dynamic=cc+['-O1',str(source/'dynamic_probe.c'),'-o',str(tree/'bin/dynamic_probe')]
    if args.mode!='dynamic':
        static.insert(len(cc),'-DHANDOFF_APPLE_LAUNCHD=1')
        dynamic.insert(len(cc),'-DCHECK_SYSTEM_USERS=1')
        if core_manifest: static.insert(len(cc),'-DINIT_CORE_SERVICES=1')
        if provider_manifest: static.insert(len(cc),'-DINIT_USERMANAGER_BOOT=1')
        if preferences_manifest: static.insert(len(cc),'-DINIT_PREFERENCES_BOOT=1')
        if backboard_manifest: static.insert(len(cc),'-DINIT_BACKBOARD_BOOT=1')
        if containers_manifest: static.insert(len(cc),'-DINIT_CONTAINER_BOOT=1')
    subprocess.run(static,check=True);subprocess.run(dynamic,check=True)
    compile_commands=[static,dynamic]
    source_names=['dynamic_init.c','dynamic_probe.c','abi_probe.c']
    extra_sources=[]
    diagnostic_signing=None
    bridge_signing=[]
    binaries=['sbin/launchd','bin/dynamic_probe','sbin/launchd.apple','usr/lib/dyld']
    if args.mode!='dynamic':
        bootstrap=cc+['-O1',str(source/'bootstrap_probe.c'),str(source/'audit_probe.c'),'-o',str(tree/'bin/bootstrap_probe')]
        source_names.append('audit_probe.c')
        if provider_manifest: bootstrap.insert(len(cc),'-DCHECK_USERMANAGER=1')
        if provider_manifest:
            bootstrap+=[str(source/'ramfs_probe.c'),str(source/'muser_probe.c'),'-framework','CoreFoundation']
            source_names+=['ramfs_probe.c','muser_probe.c']
        if core_manifest: bootstrap.insert(len(cc),'-DCHECK_CORE_SERVICES=1')
        if preferences_manifest:
            bootstrap.insert(len(cc),'-DCHECK_PREFERENCES=1')
            bootstrap.append(str(source/'preferences_probe.c'));source_names.append('preferences_probe.c')
        if fsevents_manifest: bootstrap.insert(len(cc),'-DCHECK_FSEVENTS=1')
        if backboard_manifest: bootstrap.insert(len(cc),'-DCHECK_BACKBOARD=1')
        if locale_check: bootstrap.insert(len(cc),'-DCHECK_LOCALE=1')
        if args.check_touch_bridge: bootstrap.insert(len(cc),'-DCHECK_TOUCH_BRIDGE=1')
        if args.check_input_queue: bootstrap.insert(len(cc),'-DCHECK_INPUT_QUEUE=1')
        if args.check_hid_service: bootstrap.insert(len(cc),'-DCHECK_HID_SERVICE=1')
        if args.check_hid_encoding: bootstrap.insert(len(cc),'-DCHECK_HID_ENCODING=1')
        subprocess.run(bootstrap,check=True);compile_commands.append(bootstrap)
        source_names.append('bootstrap_probe.c');binaries+=['bin/bootstrap_probe','usr/libexec/xpcproxy']
        if provider_manifest: binaries+=['usr/libexec/usermanagerd']
        if provider_manifest:
            nsxpc=cc+['-fobjc-arc','-fblocks','-O1',str(source/'nsxpc_probe.m'),'-framework','Foundation',
                      '-o',str(tree/'bin/nsxpc_probe')]
            subprocess.run(nsxpc,check=True);compile_commands.append(nsxpc)
            source_names+=['nsxpc_probe.m','session_state.h'];binaries.append('bin/nsxpc_probe')
        if core_manifest: binaries+=['usr/libexec/logd','usr/sbin/notifyd']
        if helper_manifest: binaries+=['usr/libexec/logd_helper']
        if preferences_manifest: binaries+=['usr/sbin/cfprefsd']
        if fsevents_manifest:
            fsevents=cc+['-O1',str(source/'fsevents_probe.c'),'-framework','CoreFoundation',
                '-F'+str(sdk/'System/Library/PrivateFrameworks'),'-framework','FSEvents','-o',str(tree/'bin/fsevents_probe')]
            subprocess.run(fsevents,check=True);compile_commands.append(fsevents)
            source_names.append('fsevents_probe.c');binaries+=['usr/libexec/fseventsd','bin/fsevents_probe']
        if backboard_manifest:
            desktop=cc+['-O1',str(source/'desktop_probe.c'),'-framework','CoreFoundation','-framework','IOKit','-o',str(tree/'bin/desktop_probe')]
            subprocess.run(desktop,check=True);compile_commands.append(desktop)
            source_names.append('desktop_probe.c');binaries+=['usr/libexec/backboardd','bin/desktop_probe']
        if containers_manifest:binaries+=['usr/libexec/containermanagerd','usr/libexec/containermanagerd_system']
        if locale_check:
            locale=cc+['-fobjc-arc','-O1',str(source/'locale_probe.m'),'-framework','Foundation','-o',str(tree/'bin/locale_probe')]
            subprocess.run(locale,check=True);compile_commands.append(locale)
            source_names.append('locale_probe.m');binaries.append('bin/locale_probe')
    if args.check_input_queue:
        queue=cc+['-O1','-Wall','-Wextra','-Werror','-I'+str(ROOT/'xnu/files/bsd'),
            str(source/'input_queue_probe.c'),'-o',str(tree/'bin/input_queue_probe')]
        subprocess.run(queue,check=True);compile_commands.append(queue)
        source_names.append('input_queue_probe.c');binaries.append('bin/input_queue_probe')
        extra_sources+=[ROOT/'xnu/files/bsd/sys/lemonades_input.h',ROOT/'xnu/files/bsd/sys/redwood_input.h']
    if args.check_hid_encoding:
        common=ROOT/'common/lemonades'
        encoding=cc+['-O1','-Wall','-Wextra','-Werror','-I'+str(common),'-I'+str(ROOT/'xnu/files/bsd'),
            str(source/'hid_touch_probe.c'),str(source/'hid_touch_event.c'),str(common/'hid_touch.c'),
            '-framework','CoreFoundation','-framework','IOKit','-o',str(tree/'bin/hid_touch_probe')]
        subprocess.run(encoding,check=True);compile_commands.append(encoding)
        source_names+=['hid_touch_probe.c','hid_touch_event.c','hid_touch_event.h']
        extra_sources+=[common/'hid_touch.c',common/'hid_touch.h',ROOT/'xnu/files/bsd/sys/redwood_input.h']
        binaries.append('bin/hid_touch_probe')
    if args.check_hid_service:
        common=ROOT/'common/lemonades'
        service=cc+['-O1','-Wall','-Wextra','-Werror','-fblocks','-I'+str(common),
            str(source/'hid_service_probe.c'),str(source/'hid_touch_event.c'),str(common/'hid_touch.c'),
            '-framework','CoreFoundation','-framework','IOKit','-o',str(tree/'bin/hid_service_probe')]
        if args.check_input_queue:
            service+=['-DCHECK_INPUT_QUEUE=1','-I'+str(ROOT/'xnu/files/bsd'),str(common/'hid_stream.c')]
            extra_sources+=[common/'hid_stream.c',common/'hid_stream.h']
        subprocess.run(service,check=True);compile_commands.append(service)
        if args.hid_service_permissions:
            entitlements=source/'hid_service_probe.entitlements'
            expected_permissions={'com.apple.private.hid.client.event-dispatch':True,'com.apple.private.hid.client.event-monitor':True}
            if plistlib.loads(entitlements.read_bytes())!=expected_permissions:raise ValueError('unexpected synthetic HID permissions')
            binary=tree/'bin/hid_service_probe'
            sign=['/usr/bin/codesign','--force','--sign','-','--identifier','net.hackios9r.synthetic-hid-probe',
                  '--entitlements',str(entitlements),'--generate-entitlement-der',str(binary)]
            subprocess.run(sign,check=True)
            embedded=subprocess.check_output(['/usr/bin/codesign','--display','--entitlements','-','--xml',str(binary)])
            if plistlib.loads(embedded)!=expected_permissions:raise ValueError('embedded HID permissions mismatch')
            (out/'hid-service-embedded-entitlements.plist').write_bytes(embedded)
            diagnostic_signing={'command':sign,'binary_sha256':sha_file(binary),'permissions':expected_permissions,
                'apple_trust_verified':False,'scope':'only self-built synthetic probe; research miniamfi accepts declarations'}
            source_names.append('hid_service_probe.entitlements')
        source_names+=['hid_service_probe.c','hid_touch_event.c','hid_touch_event.h']
        extra_sources+=[common/'hid_touch.c',common/'hid_touch.h']
        binaries.append('bin/hid_service_probe')
    if args.touch_bridge:
        common=ROOT/'common/lemonades'
        targets=[('touch_bridge','usr/libexec/lemonades-touch-bridge','event-dispatch')]
        if args.check_touch_bridge:targets.append(('touch_bridge_probe','bin/touch_bridge_probe','event-monitor'))
        for name,destination,permission in targets:
            command=cc+['-O1','-Wall','-Wextra','-Werror','-fblocks','-I'+str(common),'-I'+str(ROOT/'xnu/files/bsd'),
                str(source/(name+'.c')),str(source/'hid_device.c'),str(source/'hid_touch_event.c'),
                str(common/'hid_touch.c'),str(common/'hid_stream.c'),
                '-framework','CoreFoundation','-framework','IOKit','-o',str(tree/destination)]
            if args.test_integrated_touch:command.append('-DTEST_INTEGRATED_TOUCH=1')
            if args.check_hid_server_restart and name=='touch_bridge_probe':command.append('-DCHECK_HID_SERVER_RESTART=1')
            subprocess.run(command,check=True);compile_commands.append(command)
            binary=tree/destination;entitlements=source/(name+'.entitlements')
            expected={'com.apple.private.hid.client.'+permission:True}
            if plistlib.loads(entitlements.read_bytes())!=expected:raise ValueError('unexpected bridge permissions')
            sign=['/usr/bin/codesign','--force','--sign','-','--identifier','net.hackios9r.'+name,
                '--entitlements',str(entitlements),'--generate-entitlement-der',str(binary)]
            subprocess.run(sign,check=True)
            embedded=subprocess.check_output(['/usr/bin/codesign','--display','--entitlements','-','--xml',str(binary)])
            if plistlib.loads(embedded)!=expected:raise ValueError('embedded bridge permissions mismatch')
            (out/(name+'-embedded-entitlements.plist')).write_bytes(embedded)
            bridge_signing.append({'command':sign,'binary_sha256':sha_file(binary),'permissions':expected,'apple_trust_verified':False})
            source_names+=[name+'.c',name+'.entitlements'];binaries.append(destination)
        source_names+=['hid_client_abi.h','hid_device.c','hid_touch_event.c','hid_touch_event.h']
        extra_sources+=[common/name for name in ['hid_touch.c','hid_touch.h','hid_stream.c','hid_stream.h']]
        extra_sources+=[ROOT/'xnu/files/bsd/sys'/name for name in ['lemonades_input.h','redwood_input.h']]
        shutil.copyfile(jobs/'net.hackios9r.touch-bridge.plist',out/'touch-bridge-job.plist')
    source_names=list(dict.fromkeys(source_names));extra_sources=list(dict.fromkeys(extra_sources))
    source_paths=[source/name for name in source_names]+extra_sources
    for path in source_paths:
        inputs[str(path.relative_to(ROOT))]=sha_file(path)
    for name in binaries:
        inspection=subprocess.check_output(['xcrun','otool','-arch','arm64','-hv','-L',str(tree/name)],text=True)
        (out/(Path(name).name+'.macho.txt')).write_text(inspection)
        if 'ARM64' not in inspection or 'ALL' not in inspection: raise ValueError('arm64 slice missing: '+name)
    snapshots=out/'sources';snapshots.mkdir()
    for path in [Path(__file__).resolve(),*source_paths,
                 Path(__file__).with_name('dynamic-userland-lock.json'),reference/'tools/apfs/mkapfs.py']:
        shutil.copyfile(path,snapshots/path.name)
    ownership=out/'ownership.tsv';ownership.write_text(''.join(manifest_lines))
    image=out/'dynamic-root.apfs'
    command=['python3',str(reference/'tools/apfs/mkapfs.py'),'-z','-o',str(image),f'Dynamic={tree},manifest={ownership}']
    with (out/'image-build.log').open('w') as log: subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    report={'mode':args.mode,'scope':('APFS diagnostic PID1 plus real Apple dyld and arm64 shared cache; Apple launchd is stored but not executed' if args.mode=='dynamic' else 'Diagnostic PID1 hands off to original Apple launchd with one bootstrap test job; not a complete iOS root'),
        'inputs_sha256':inputs,'apfs_writer_commit':commit,'compile_commands':compile_commands,
        'image_command':command,'image':str(image),'image_sha256':sha_file(image),'image_size':image.stat().st_size,
        'runtime_cache_files':len(names),'apple_binaries_modified':False}
    report['source_snapshots_sha256']={path.name:sha_file(path) for path in snapshots.iterdir()}
    report['extraction_manifests_sha256']={str(path):sha_file(path) for path in [
        args.rootfs.with_name(args.rootfs.name+'-extraction.json'),args.cache.with_name(args.cache.name+'-extraction.json')]}
    if provider_manifest:
        path=args.provider.with_name(args.provider.name+'-extraction.json')
        report['extraction_manifests_sha256'][str(path)]=sha_file(path)
        report['scope']='Original launchd/xpcproxy/usermanagerd and bootstrap probe; tests persona initialization, not full iOS'
        report['provider_job_changes']={'StandardOutPath':'/dev/console','StandardErrorPath':'/dev/console',
            'EnvironmentVariables.OS_ACTIVITY_DT_MODE':'YES'}
        report['provider_boot_task']=['/usr/libexec/usermanagerd','--init']
        report['provider_boot_task_environment']={'XPC_SERVICES_UNAVAILABLE':'1','XPC_NULL_BOOTSTRAP':'1','OS_ACTIVITY_DT_MODE':'YES'}
    report['core_services']=bool(core_manifest)
    report['log_helper']=bool(helper_manifest)
    report['preferences']=bool(preferences_manifest)
    report['fsevents']=bool(fsevents_manifest)
    report['backboard']=bool(backboard_manifest)
    report['backboard_config']=bool(backboard_config_manifest)
    report['containers']=bool(containers_manifest)
    report['locale_check']=locale_check
    report['hid_encoding_check']=args.check_hid_encoding
    report['hid_service_check']=args.check_hid_service
    report['input_queue_check']=args.check_input_queue
    report['hid_service_signing']=diagnostic_signing
    report['test_integrated_touch']=args.test_integrated_touch
    report['touch_bridge']=args.touch_bridge
    report['touch_bridge_check']=args.check_touch_bridge
    report['hid_server_restart_check']=args.check_hid_server_restart
    report['touch_bridge_signing']=bridge_signing
    if args.touch_bridge:report['touch_bridge_job_sha256']=sha_file(out/'touch-bridge-job.plist')
    report['icu']=bool(icu_manifest)
    if icu_manifest:
        path=args.icu.with_name(args.icu.name+'-extraction.json')
        report['extraction_manifests_sha256'][str(path)]=sha_file(path)
    if containers_manifest:
        path=args.containers.with_name(args.containers.name+'-extraction.json')
        report['extraction_manifests_sha256'][str(path)]=sha_file(path)
        report['container_job_changes']={'StandardOutPath':'/dev/console','StandardErrorPath':'/dev/console',
            'EnvironmentVariables.OS_ACTIVITY_DT_MODE':'YES'}
    if backboard_config_manifest:
        path=args.backboard_config.with_name(args.backboard_config.name+'-extraction.json')
        report['extraction_manifests_sha256'][str(path)]=sha_file(path)
    if backboard_manifest:
        path=args.backboard.with_name(args.backboard.name+'-extraction.json')
        report['extraction_manifests_sha256'][str(path)]=sha_file(path)
        report['backboard_job_changes']={'StandardOutPath':'/private/var/mobile/Library/Logs/backboard-bringup.log',
            'StandardErrorPath':'/private/var/mobile/Library/Logs/backboard-bringup.log',
            'EnvironmentVariables.OS_ACTIVITY_DT_MODE':'YES'}
    if fsevents_manifest:
        path=args.fsevents.with_name(args.fsevents.name+'-extraction.json')
        report['extraction_manifests_sha256'][str(path)]=sha_file(path)
        report['fsevents_job_changes']={'StandardOutPath':'/dev/console','StandardErrorPath':'/dev/console',
            'EnvironmentVariables.OS_ACTIVITY_DT_MODE':'YES'}
    if preferences_manifest:
        path=args.preferences.with_name(args.preferences.name+'-extraction.json')
        report['extraction_manifests_sha256'][str(path)]=sha_file(path)
        report['preferences_job_changes']={'StandardOutPath':'/dev/console','StandardErrorPath':'/dev/console',
            'EnvironmentVariables.OS_ACTIVITY_DT_MODE':'YES'}
    if helper_manifest:
        path=args.log_helper.with_name(args.log_helper.name+'-extraction.json')
        report['extraction_manifests_sha256'][str(path)]=sha_file(path)
        report['helper_job_changes']={'StandardOutPath':'/dev/console','StandardErrorPath':'/dev/console',
                                     'EnvironmentVariables.OS_ACTIVITY_DT_MODE':'YES'}
    if core_manifest:
        path=args.core_services.with_name(args.core_services.name+'-extraction.json')
        report['extraction_manifests_sha256'][str(path)]=sha_file(path)
        report['core_job_changes']={'notifyd':report['provider_job_changes'],
            'logd':{'StandardOutPath':'/private/var/db/diagnostics/bringup.log',
                    'StandardErrorPath':'/private/var/db/diagnostics/bringup.log',
                    'EnvironmentVariables.OS_ACTIVITY_DT_MODE':'YES'}}
    (out/'build.json').write_text(json.dumps(report,indent=2)+'\n');print(out/'build.json',flush=True)

if __name__=='__main__': main()
