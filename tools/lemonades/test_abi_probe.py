import importlib.util
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('kernel_smoke', Path(__file__).with_name('kernel-smoke.py'))
smoke=importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

class ProbeLogTests(unittest.TestCase):
    def good(self, program='abi'):
        markers=smoke.expected_markers(program)
        return '\n'.join(markers[:-1]+['panic(cpu 0 caller 0x123): '+markers[-1]])

    def test_complete_probe(self):
        self.assertTrue(smoke.check_log(self.good(),'abi')['passed'])
        self.assertTrue(smoke.check_log(self.good('hello'),'hello')['passed'])

    def test_each_missing_stage_fails(self):
        for marker in smoke.expected_markers('abi'):
            with self.subTest(marker=marker):
                self.assertFalse(smoke.check_log(self.good().replace(marker,''),'abi')['passed'])

    def test_success_banner_cannot_hide_failure(self):
        self.assertFalse(smoke.check_log(self.good()+'\nABI FAIL: copy-on-write isolation','abi')['passed'])
        self.assertFalse(smoke.check_log(self.good()+'\npanic(cpu 0): unexpected exception','abi')['passed'])

    def test_wrong_order_and_wrong_exit_fail(self):
        log=self.good().replace('ABI PASS vm','later').replace('ABI COMPLETE v1','ABI PASS vm').replace('later','ABI COMPLETE v1')
        self.assertFalse(smoke.check_log(log,'abi')['passed'])
        self.assertFalse(smoke.check_log(self.good().replace('exit status 0','exit status 1'),'abi')['passed'])

    def test_hello_is_not_abi_evidence(self):
        self.assertFalse(smoke.check_log(self.good('hello'),'abi')['passed'])

    def test_bsd_checks_are_not_mach_evidence(self):
        self.assertFalse(smoke.check_log(self.good('abi'),'mach')['passed'])
        self.assertTrue(smoke.check_log(self.good('mach'),'mach')['passed'])
        for marker in smoke.expected_markers('mach'):
            self.assertFalse(smoke.check_log(self.good('mach').replace(marker,''),'mach')['passed'])

    def test_dynamic_requires_child_success_and_clean_parent_exit(self):
        log=self.good('dynamic')
        self.assertTrue(smoke.check_log(log,'dynamic')['passed'])
        for marker in smoke.expected_markers('dynamic'):
            self.assertFalse(smoke.check_log(log.replace(marker,''),'dynamic')['passed'])
        self.assertFalse(smoke.check_log(log+'\nABI FAIL: dynamic child status','dynamic')['passed'])
        self.assertFalse(smoke.check_log(log.replace('exit status 0','exit status 1'),'dynamic')['passed'])
        self.assertFalse(smoke.check_log(self.good('abi'),'dynamic')['passed'])

    def test_launchd_requires_service_checks_and_no_panic(self):
        log='\n'.join(smoke.expected_markers('launchd')).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]) <Notice>: exited due to exit(0)'
        self.assertTrue(smoke.check_log(log,'launchd')['passed'])
        for marker in smoke.expected_markers('launchd'):
            self.assertFalse(smoke.check_log(log.replace(marker,''),'launchd')['passed'])
        self.assertFalse(smoke.check_log(log+'\nBOOTSTRAP FAIL: lookup','launchd')['passed'])
        self.assertFalse(smoke.check_log(log+'\npanic(cpu 0): initproc failed to start','launchd')['passed'])
        self.assertFalse(smoke.check_log(self.good('dynamic'),'launchd')['passed'])
        for a,b in [('exit(0)','exit(1)'),('probe [4]','probe [5]'),('ppid=1','ppid=3'),
                    ('Successfully spawned bootstrap_probe[4]','Successfully spawned unrelated[4]')]:
            self.assertFalse(smoke.check_log(log.replace(a,b),'launchd')['passed'])

    def test_usermanager_needs_actual_persona_not_only_a_started_job(self):
        log='\n'.join(smoke.expected_markers('usermanager')).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]) <Notice>: exited due to exit(0)'
        self.assertTrue(smoke.check_log(log,'usermanager')['passed'])
        for marker in smoke.expected_markers('usermanager'):
            self.assertFalse(smoke.check_log(log.replace(marker,''),'usermanager')['passed'])
        missing=log.replace('USERMANAGER PASS system-proxy','Successfully spawned usermanagerd[5]')
        self.assertFalse(smoke.check_log(missing,'usermanager')['passed'])
        self.assertFalse(smoke.check_log(log+'\nBOOTSTRAP FAIL: usermanager system-proxy unavailable','usermanager')['passed'])
        self.assertFalse(smoke.check_log(log+'\npanic(cpu 0): provider crash','usermanager')['passed'])
        for error in ('transport domain=NSCocoaErrorDomain code=4097',
                      'response timeout', 'unexpected persona response'):
            with self.subTest(nsxpc=error):
                verdict=smoke.check_log(log+'\nNSXPC FAIL '+error,'usermanager')
                self.assertFalse(verdict['passed'])
                self.assertEqual(verdict['probe_failures'], ['NSXPC FAIL '+error])

    def test_core_services_require_real_notification_marker(self):
        log='\n'.join(smoke.expected_markers('usermanager',True)).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]) <Notice>: exited due to exit(0)'
        self.assertTrue(smoke.check_log(log,'usermanager',True)['passed'])
        self.assertFalse(smoke.check_log(log.replace('CORE PASS notify-cross-process','Successfully spawned notifyd[7]'),
                                         'usermanager',True)['passed'])

    def test_preferences_require_roundtrip_and_original_daemon_spawn(self):
        log='\n'.join(smoke.expected_markers('usermanager',True,True)).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]) <Notice>: exited due to exit(0)'
        daemon='\n(user/501/com.apple.cfprefsd.xpc.daemon [20]) <Notice>: Successfully spawned cfprefsd[20]'
        self.assertFalse(smoke.check_log(log,'usermanager',True,True)['passed'])
        log+=daemon
        self.assertTrue(smoke.check_log(log,'usermanager',True,True)['passed'])
        for before,after in [('PREFS PASS cross-process',''),('PREFS PASS mobile-isolation',''),
                             ('spawned cfprefsd[20]','spawned cfprefsd[21]')]:
            self.assertFalse(smoke.check_log(log.replace(before,after),'usermanager',True,True)['passed'])
        self.assertFalse(smoke.check_log(log+'\nBOOTSTRAP FAIL: preferences saved value','usermanager',True,True)['passed'])

    def test_fsevents_requires_callback_and_provider(self):
        log='\n'.join(smoke.expected_markers('usermanager',True,True,True)).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]) <Notice>: exited due to exit(0)'
        log+='\n(user/501/com.apple.cfprefsd.xpc.daemon [20]) <Notice>: Successfully spawned cfprefsd[20]'
        self.assertFalse(smoke.check_log(log,'usermanager',True,True,True)['passed'])
        log+='\n(system/com.apple.fseventsd [21]) <Notice>: Successfully spawned fseventsd[21]'
        self.assertTrue(smoke.check_log(log,'usermanager',True,True,True)['passed'])
        for before,after in [('FSEVENTS PASS file-create',''),('FSEVENTS PASS directory-delete',''),('PREFS PASS api-live-refresh',''),
                             ('PREFS PASS external-vnode-events',''),('PREFS PASS external-refresh',''),
                             ('spawned fseventsd[21]','spawned fseventsd[22]')]:
            self.assertFalse(smoke.check_log(log.replace(before,after),'usermanager',True,True,True)['passed'])
        for error in ['start stream','callback timeout']:
            self.assertFalse(smoke.check_log(log+'\nFSEVENTS FAIL '+error,'usermanager',True,True,True)['passed'])

    def test_backboard_requires_rpc_marker_and_original_live_process(self):
        log='\n'.join(smoke.expected_markers('usermanager',True,True,True,True)).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]): exited due to exit(0)'
        log+='\n(user/501/com.apple.cfprefsd.xpc.daemon [20]): Successfully spawned cfprefsd[20]'
        log+='\n(system/com.apple.fseventsd [21]): Successfully spawned fseventsd[21]'
        check=lambda text:smoke.check_log(text,'usermanager',True,True,True,True)['passed']
        self.assertFalse(check(log))
        log+='\n(user/501/com.apple.backboardd [22]): Successfully spawned backboardd[22]'
        self.assertTrue(check(log))
        for before,after in [('DESKTOP PASS hid-services',''),('spawned backboardd[22]','spawned backboardd[23]')]:
            self.assertFalse(check(log.replace(before,after)))
        self.assertFalse(check(log+'\n(user/501/com.apple.backboardd [22]): exited due to signal(6)'))
        self.assertFalse(check(log+'\nDESKTOP FAIL no HID services'))

    def test_locale_preflight_cannot_pass_on_creation_only_or_failure(self):
        log='\n'.join(smoke.expected_markers('launchd',locale_check=True)).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]): exited due to exit(0)'
        check=lambda text:smoke.check_log(text,'launchd',locale_check=True)['passed']
        self.assertTrue(check(log))
        self.assertFalse(check(log.replace('LOCALE PASS iso8601','LOCALE CFDateFormatterCreate nonnull=1')))
        self.assertFalse(check(log+'\nLOCALE FAIL CF formatter unavailable'))

    def test_hid_encoding_does_not_replace_device_enumeration(self):
        log='\n'.join(smoke.expected_markers('launchd',hid_encoding_check=True)).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]): exited due to exit(0)'
        self.assertTrue(smoke.check_log(log,'launchd',hid_encoding_check=True)['passed'])
        self.assertFalse(smoke.check_log(log.replace('HID TOUCH PASS event-encoding',''),'launchd',hid_encoding_check=True)['passed'])
        self.assertFalse(smoke.check_log(log.replace('HID TOUCH PASS device-profile-encoding',''),'launchd',hid_encoding_check=True)['passed'])
        self.assertFalse(smoke.check_log(log+'\nHID TOUCH FAIL fields','launchd',hid_encoding_check=True)['passed'])
        self.assertFalse(smoke.check_log(log,'launchd',backboard=True,hid_encoding_check=True)['passed'])

    def test_synthetic_hid_requires_delivery_and_removal_not_only_registration(self):
        log='\n'.join(smoke.expected_markers('launchd',hid_service_check=True)).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]): exited due to exit(0)'
        check=lambda text:smoke.check_log(text,'launchd',hid_service_check=True)['passed']
        self.assertTrue(check(log))
        for marker in ['synthetic-registration','synthetic-delivery','synthetic-removal']:
            self.assertFalse(check(log.replace('HID SERVICE PASS '+marker,'')))
        self.assertFalse(check(log+'\nHID SERVICE FAIL removal timeout'))
        self.assertFalse(smoke.check_log(log,'launchd',backboard=True,hid_service_check=True)['passed'])
        self.assertFalse(check(log.replace('HID SERVICE PASS synthetic-delivery', 'HID SERVICE send accepted=1')))

    def test_snapshot_queue_is_required_separately_from_hid_delivery(self):
        log='\n'.join(smoke.expected_markers('launchd',hid_service_check=True,input_queue_check=True)).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log+='\n(user/501/net.hackios9r.bootstrap-probe [4]): exited due to exit(0)'
        check=lambda value:smoke.check_log(value,'launchd',hid_service_check=True,input_queue_check=True)['passed']
        self.assertTrue(check(log))
        self.assertFalse(check(log.replace('INPUT QUEUE PASS select-wakeup','')))
        self.assertFalse(check(log.replace('INPUT QUEUE PASS kernel-contract','')))
        self.assertFalse(check(log.replace('HID SERVICE PASS synthetic-queue-delivery','')))
        self.assertFalse(check(log+'\nINPUT QUEUE FAIL copyout fault'))

    def test_bridge_requires_restart_and_clean_release(self):
        log='\n'.join(smoke.expected_markers('launchd',touch_bridge_check=True)).replace('BOOTSTRAP BEGIN v1',
            'Successfully spawned bootstrap_probe[4]\nBOOTSTRAP BEGIN v1 pid=4 ppid=1')
        log=log.replace('BRIDGE TEST PASS daemon-delivery',
            'Successfully spawned lemonades-touch-bridge[6]\nBRIDGE TEST initial pid=6 service=100\nBRIDGE TEST PASS daemon-delivery')
        log=log.replace('BRIDGE TEST PASS restart-held-contact',
            '(system/net.hackios9r.touch-bridge [6]): exited due to SIGKILL\nSuccessfully spawned lemonades-touch-bridge[25]\nBRIDGE TEST restarted pid=25 service=101\nBRIDGE TEST PASS restart-held-contact')
        log=log.replace('BRIDGE TEST PASS graceful-release-stop',
            '(system/net.hackios9r.touch-bridge [25]): exited due to exit(0)\nBRIDGE TEST PASS graceful-release-stop')
        log=log.replace('BRIDGE TEST PASS synthetic-default-rejected',
            'BRIDGE stopped: synthetic input rejected\nBRIDGE TEST PASS synthetic-default-rejected')
        log+='\n(system/net.hackios9r.bootstrap-probe [4]): exited due to exit(0)'
        check=lambda value:smoke.check_log(value,'launchd',touch_bridge_check=True)['passed']
        self.assertTrue(check(log))
        for marker in ['device-event-profile','daemon-delivery','restart-held-contact','graceful-release-stop','synthetic-default-rejected']:
            self.assertFalse(check(log.replace('BRIDGE TEST PASS '+marker,'')))
        for evidence in ['exited due to SIGKILL','Successfully spawned lemonades-touch-bridge[25]','exited due to exit(0)','BRIDGE stopped: synthetic input rejected']:
            self.assertFalse(check(log.replace(evidence,'')))
        self.assertFalse(check(log.replace('pid=25 service=101','pid=6 service=100')))
        self.assertFalse(check(log+'\nBRIDGE TEST FAIL shutdown release'))
        self.assertFalse(smoke.check_log(log,'launchd',backboard=True,touch_bridge_check=True)['passed'])

    def test_hid_server_fault_requires_matched_recovery_and_rejects_extra_exits(self):
        log='\n'.join([
            'Successfully spawned backboardd[7]',
            'BRIDGE SERVER fault server=7 bridge=25 probe=24',
            '(user/501/com.apple.backboardd [7]): exited due to SIGKILL | sent by touch_bridge_probe[24]',
            'BRIDGE EXIT pid=25 status=75 frames=1 reset=1',
            'Successfully spawned backboardd[26]',
            'Successfully spawned lemonades-touch-bridge[27]',
            'BRIDGE SERVER recovered server=26 bridge=27 service=102',
            'BRIDGE TEST PASS server-restart-held-contact'])
        check=lambda text:smoke.check_log(text,'launchd',backboard=True,hid_server_restart_check=True)
        result=check(log)
        self.assertTrue(result['server_restart_verified'])
        self.assertFalse(result['backboard_exits'])
        self.assertFalse(result['passed'])  # recovery does not replace the desktop/system checks
        for evidence in ['reset=1','Successfully spawned backboardd[26]','BRIDGE TEST PASS server-restart-held-contact']:
            self.assertFalse(check(log.replace(evidence,''))['server_restart_verified'])
        self.assertFalse(check(log.replace('probe[24]','probe[99]'))['server_restart_verified'])
        self.assertFalse(check(log.replace('server=26','server=7'))['server_restart_verified'])
        self.assertTrue(check(log+'\n(user/501/com.apple.backboardd [26]): exited due to SIGSEGV')['backboard_exits'])
        self.assertTrue(smoke.check_log(log,'launchd',backboard=True)['backboard_exits'])

class ProbeSourceContractTests(unittest.TestCase):
    def test_syscall_numbers_match_pinned_xnu(self):
        source=ROOT/'out/lemonades/xnu-platform-src'
        commit='c54f35ca767986246321eb901baf8f5ff7923f6a'
        master=subprocess.check_output(['git','-C',str(source),'show',commit+':bsd/kern/syscalls.master'],text=True)
        probe=(ROOT/'tools/lemonades/userland/abi_probe.c').read_text()
        definitions=re.findall(r'SYS_(\w+)=(\d+)',probe)
        self.assertEqual(len(definitions),14)
        for name, number in definitions:
            kernel_name='sys_close' if name=='close' else name
            self.assertRegex(master, r'(?m)^'+number+r'\s+[^\n]*\b'+kernel_name+r'\(')

    def test_mach_traps_match_pinned_xnu(self):
        source=ROOT/'out/lemonades/xnu-platform-src'
        commit='c54f35ca767986246321eb901baf8f5ff7923f6a'
        master=subprocess.check_output(['git','-C',str(source),'show',commit+':osfmk/kern/syscall_sw.c'],text=True)
        probe=(ROOT/'tools/lemonades/userland/mach_probe.c').read_text()
        names={'allocate':'_kernelrpc_mach_port_allocate_trap',
               'deallocate':'_kernelrpc_mach_port_deallocate_trap',
               'mod_refs':'_kernelrpc_mach_port_mod_refs_trap',
               'insert_right':'_kernelrpc_mach_port_insert_right_trap',
               'task_self':'task_self_trap','msg2':'mach_msg2_trap'}
        definitions=dict(re.findall(r'MT_(\w+)=(\d+)',probe))
        self.assertEqual(set(definitions),set(names))
        for name,number in definitions.items():
            self.assertRegex(master,r'/\* '+number+r' \*/ MACH_TRAP\('+names[name]+',')

    def test_dynamic_syscalls_match_pinned_xnu(self):
        source=ROOT/'out/lemonades/xnu-platform-src'
        master=subprocess.check_output(['git','-C',str(source),'show',
            'c54f35ca767986246321eb901baf8f5ff7923f6a:bsd/kern/syscalls.master'],text=True)
        probe=(ROOT/'tools/lemonades/userland/dynamic_init.c').read_text()
        definitions=re.findall(r'DYN_SYS_(\w+)=(\d+)',probe)
        self.assertEqual(len(definitions),6)
        for name,number in definitions:
            kernel_name='sys_dup2' if name=='dup2' else name
            self.assertRegex(master,r'(?m)^'+number+r'\s+[^\n]*\b'+kernel_name+r'\(')

    def test_msg2_options_and_mig_id(self):
        source=ROOT/'out/lemonades/xnu-platform-src'
        commit='c54f35ca767986246321eb901baf8f5ff7923f6a'
        header=subprocess.check_output(['git','-C',str(source),'show',commit+':osfmk/mach/message.h'],text=True)
        probe=(ROOT/'tools/lemonades/userland/mach_probe.c').read_text()
        for suffix in ['MQ_CALL','KOBJECT_CALL']:
            local=re.search(r'#define PROBE_MACH64_SEND_'+suffix+r' (0x[0-9a-f]+)ull',probe)[1]
            upstream=re.search(r'MACH64_SEND_'+suffix+r'\s*=\s*(0x[0-9a-f]+)ull',header)[1]
            self.assertEqual(int(local,16),int(upstream,16))
        sdk=(ROOT/'out/lemonades/native-deps/iPhoneOS16.5.xnu.sdk/usr/include/mach/task.h').read_text()
        self.assertIn('{ "task_info", 3405 }',sdk)
        self.assertIn('request->Head.msgh_id=3405;',probe)

if __name__=='__main__': unittest.main()
