"""Session consistency and bounded file handling; all state and host flags are fixtures."""
from pathlib import Path
import copy
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
ID='MKBUserSessionID'
FG='MKBUserSessionForeground'


@unittest.skipUnless(sys.platform=='darwin','requires host Foundation')
class SessionStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        source=r'''
#import <Foundation/Foundation.h>
#include <mach/mach.h>
static const char *state_path;
static uint32_t fixture_flags;
static kern_return_t fixture_status;
#define SESSION_STATE_PATH state_path
#define SESSION_STATE_OWNER getuid()
#include "session_state.h"
kern_return_t host_get_multiuser_config_flags(host_t host,uint32_t *flags) {
    (void)host;*flags=fixture_flags;return fixture_status;
}
int main(int argc,char **argv) {
    @autoreleasepool {
        if(argc!=6)return 2;
        state_path=argv[3];fixture_flags=(uint32_t)strtoull(argv[4],NULL,0);fixture_status=atoi(argv[5]);
        id attributes=[NSPropertyListSerialization propertyListWithData:
            [NSData dataWithContentsOfFile:@(argv[2])] options:0 format:NULL error:NULL];
        if(!strcmp(argv[1],"read"))return check_session_state(attributes)?0:1;
        id saved=[NSPropertyListSerialization propertyListWithData:
            [NSData dataWithContentsOfFile:@(argv[3])] options:0 format:NULL error:NULL];
        return validate_session_state(attributes,saved,fixture_flags)?0:1;
    }
}
'''
        (cls.root/'session_state.h').write_text((ROOT/'tools/lemonades/userland/session_state.h').read_text())
        (cls.root/'fixture.m').write_text(source);cls.exe=cls.root/'fixture'
        result=subprocess.run(['xcrun','clang','-fobjc-arc','-fblocks','-Werror',str(cls.root/'fixture.m'),
                               '-framework','Foundation','-o',str(cls.exe)],capture_output=True,text=True)
        if result.returncode: cls.temp.cleanup();raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.attributes={ID:501,FG:True,'MKBUserSessionHomeDir':'/var/mobile'}
        self.saved={'sessions':[copy.deepcopy(self.attributes),{ID:502,FG:False}]}
        self.attr_path=self.root/'attributes.plist';self.state_path=self.root/'state.plist'
        self.attr_path.write_bytes(plistlib.dumps(self.attributes))
        self.state_path.unlink(missing_ok=True)
        self.state_path.write_bytes(plistlib.dumps(self.saved));self.state_path.chmod(0o600)

    def check(self,attributes=None,saved=None,flags=501,passed=True,mode='compare',status=0):
        if attributes is not None:self.attr_path.write_bytes(plistlib.dumps(attributes))
        if saved is not None:self.state_path.write_bytes(plistlib.dumps(saved))
        result=subprocess.run([str(self.exe),mode,str(self.attr_path),str(self.state_path),str(flags),str(status)],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0 if passed else 1,result.stdout+result.stderr)

    def test_matching_records_and_mode_mask(self):
        self.check();self.check(flags=0xc00001f5)
        data=plistlib.dumps(self.saved['sessions'],fmt=plistlib.FMT_BINARY)
        self.check(saved={'nested':data})
        self.check(saved=self.saved,mode='read')

    def test_identity_types_and_kernel_mismatch(self):
        for value in (True,-1,1<<30,1<<63,501.0,'501',502):
            with self.subTest(value=value):
                attributes={**self.attributes,ID:value}
                self.check(attributes=attributes,passed=False)
        self.check(attributes=self.attributes,flags=502,passed=False)

    def test_foreground_uniqueness_and_full_dictionary_match(self):
        for value in (False,1,'true'):
            with self.subTest(value=value):self.check(attributes={**self.attributes,FG:value},passed=False)
        self.check(attributes=self.attributes,saved={'sessions':[self.attributes,self.attributes]},passed=False)
        self.check(saved={'sessions':[self.attributes,{ID:502,FG:True}]},passed=False)
        self.check(saved={'sessions':[{**self.attributes,'MKBUserSessionHomeDir':'/wrong'}]},passed=False)
        self.check(saved={'sessions':[{ID:502,FG:True}]},passed=False)
        self.check(saved={'sessions':[]},passed=False)
        self.check(saved=[],passed=False)

    def test_malformed_nested_records_and_limits(self):
        self.check(saved={'sessions':[self.attributes,{ID:'502',FG:False}]},passed=False)
        self.check(saved={'sessions':[self.attributes,{ID:502}]},passed=False)
        self.check(saved={'blob':b'bplist00invalid'},passed=False)
        self.check(saved={'huge':[0]*257,'sessions':[self.attributes]},passed=False)
        nested=self.saved
        for _ in range(17):nested={'nested':nested}
        self.check(saved=nested,passed=False)

    def test_rejects_unsafe_or_invalid_state_file(self):
        self.state_path.chmod(0o666);self.check(mode='read',passed=False)
        self.state_path.chmod(0o600)
        for data in (b'',b'not a plist',b'x'*1048577):
            with self.subTest(length=len(data)):
                self.state_path.write_bytes(data);self.check(mode='read',passed=False)
        self.state_path.unlink();self.state_path.symlink_to(self.attr_path)
        self.check(mode='read',passed=False)
        self.state_path.unlink();os.mkfifo(self.state_path)
        self.check(mode='read',passed=False)
        self.state_path.unlink();self.check(mode='read',passed=False)
        self.state_path.write_bytes(plistlib.dumps(self.saved))
        self.check(mode='read',status=5,passed=False)


if __name__=='__main__':unittest.main()
