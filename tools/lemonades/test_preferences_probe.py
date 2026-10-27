"""Check the real saved-plist validator against temporary fixtures, never host preferences."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform=='darwin','requires host CoreFoundation')
class PreferenceFileTests(unittest.TestCase):
    def test_saved_value_and_quiet_pending_observation(self):
        source=(ROOT/'tools/lemonades/userland/preferences_probe.c').read_text()
        prefix=r'''
#include <stdio.h>
#include <sys/stat.h>
#include <string.h>
#include <assert.h>
static const char *fixture_path;
static uid_t fixture_uid;
static FILE *fixture_fopen(const char *path,const char *mode) {
    assert(!strcmp(path,"/private/var/root/Library/Preferences/net.hackios9r.preferences-probe.plist") ||
           !strcmp(path,"/private/var/mobile/Library/Preferences/net.hackios9r.preferences-probe.plist"));
    return fopen(fixture_path,mode);
}
static int fixture_fstat(int fd,struct stat *st) {
    int result=fstat(fd,st);if(!result)st->st_uid=fixture_uid;return result;
}
#define fopen fixture_fopen
#define fstat fixture_fstat
'''
        suffix=r'''
int main(int argc,char **argv) {
    if(argc!=4 && argc!=5)return 2;fixture_path=argv[1];fixture_uid=(uid_t)atoi(argv[3]);
    if(argc==5)return saved_value_at("/private/var/mobile/Library/Preferences/net.hackios9r.preferences-probe.plist",501,"expected",atoi(argv[2]));
    return saved_value_check("expected",atoi(argv[2]));
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);c=tmp/'fixture.c';c.write_text(prefix+source+suffix);exe=tmp/'fixture'
            result=subprocess.run(['xcrun','clang','-Werror',str(c),'-framework','CoreFoundation','-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            good=plistlib.dumps({'RoundTripNonce':'expected'},fmt=plistlib.FMT_BINARY)
            cases=[(good,0o600,0,0),(plistlib.dumps({'RoundTripNonce':'old'}),0o600,0,1),
                   (plistlib.dumps({'RoundTripNonce':1}),0o600,0,1),(plistlib.dumps({}),0o600,0,1),
                   (plistlib.dumps(['expected']),0o600,0,1),(b'bad',0o600,0,1),(b'',0o600,0,1),
                   (b'x'*65537,0o600,0,1),(good,0o666,0,1),(good,0o600,501,1),(None,0o600,0,1)]
            for index,(data,mode,uid,expected) in enumerate(cases):
                path=tmp/'state.plist';path.unlink(missing_ok=True)
                if data is not None:path.write_bytes(data);path.chmod(mode)
                for quiet in (0,1):
                    with self.subTest(case=index,quiet=quiet):
                        result=subprocess.run([str(exe),str(path),str(quiet),str(uid)],capture_output=True,text=True,timeout=5)
                        self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
                        self.assertEqual('BOOTSTRAP FAIL:' in result.stdout,bool(expected and not quiet))
            path.write_bytes(good);path.chmod(0o600)
            for uid,expected in [(501,0),(0,1),(502,1)]:
                with self.subTest(mobile_owner=uid):
                    result=subprocess.run([str(exe),str(path),'1',str(uid),'mobile'],capture_output=True,text=True,timeout=5)
                    self.assertEqual(result.returncode,expected,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
