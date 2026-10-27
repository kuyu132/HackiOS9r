"""Exercise the actual probe parser with CoreFoundation and controlled kernel IDs."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(sys.platform=='darwin','requires host CoreFoundation')
class PersonaManifestTests(unittest.TestCase):
    def test_nested_manifest_matches_kernel_and_rejects_stale_or_malformed_data(self):
        source=(ROOT/'tools/lemonades/userland/bootstrap_probe.c').read_text()
        # Compile the same parser/comparison body used in the guest, not a Python reimplementation.
        body=source[source.index('struct persona_ids {'):source.index('static int check_user_state(void)')]
        prefix=r'''
#include <CoreFoundation/CoreFoundation.h>
#include <sys/types.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
static int failed(const char *s,int code) { (void)s;(void)code;return 1; }
static int bad_return;
static int kpersona_find_by_type(int type,uid_t *ids,size_t *count) {
    static const uid_t a[]={99,100},b[]={1000},c[]={199,200};
    const uid_t *values=type==4?a:type==5?b:c;size_t n=type==5?1:2;
    if (*count<n) return -1;
    memcpy(ids,values,n*sizeof(*ids));*count=n;return bad_return ? 0 : (int)n;
}
'''
        suffix=r'''
int main(int argc,char **argv) {
    if(argc!=3) return 2;
    bad_return=atoi(argv[2]);
    FILE *f=fopen(argv[1],"rb");if(!f)return 2;
    fseek(f,0,SEEK_END);long size=ftell(f);rewind(f);
    unsigned char *bytes=malloc(size);if(fread(bytes,1,size,f)!=(size_t)size)return 2;fclose(f);
    CFDataRef data=CFDataCreate(NULL,bytes,size);free(bytes);
    CFPropertyListRef p=CFPropertyListCreateWithData(NULL,data,0,NULL,NULL);CFRelease(data);
    if(!p)return 2;
    int result=match_kernel_personas(p);CFRelease(p);return result;
}
'''
        def manifest(ids,version=1):
            # The original outer schema wraps user records in bplist CFData.
            inner=plistlib.dumps({'personas':[{'UserPersonaID':n} for n in ids]},fmt=plistlib.FMT_BINARY)
            return {'UsePersonaManifestVersion':version,'UserPersonaDictionary':{'user':inner}}
        cases=[('valid',manifest([99,100,1000,199,200]),0,0),
               ('stale',manifest([99,199]),0,1),
               ('extra',manifest([99,100,1000,199,200,777]),0,1),
               ('duplicate',manifest([99,100,1000,199,200,99]),0,1),
               ('future',manifest([99,100,1000,199,200],2),0,1),
               ('string-id',manifest(['99',100,1000,199,200]),0,1),
               ('overflow',manifest([2**32,100,1000,199,200]),0,1),
               ('empty',manifest([]),0,1),
               ('zero-is-not-count',manifest([99,100,1000,199,200]),1,1),
               ('capacity',manifest(list(range(65))),0,1),
               ('corrupt',{'UsePersonaManifestVersion':1,'UserPersonaDictionary':{'user':b'bplist00corrupt'}},0,1)]
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);c=tmp/'parser.c';c.write_text(prefix+body+suffix)
            subprocess.run(['xcrun','clang','-Werror',str(c),'-framework','CoreFoundation','-o',str(tmp/'parser')],check=True,capture_output=True)
            for name,fixture,bad,expected in cases:
                with self.subTest(name=name):
                    p=tmp/(name+'.plist');p.write_bytes(plistlib.dumps(fixture,fmt=plistlib.FMT_BINARY))
                    result=subprocess.run([str(tmp/'parser'),str(p),str(bad)],capture_output=True,text=True)
                    self.assertEqual(result.returncode,expected,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
