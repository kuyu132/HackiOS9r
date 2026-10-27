"""Validate kernel-trailer parsing with local packets; no host IPC or credential changes."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform=='darwin','requires Mach headers')
class AuditTrailerTests(unittest.TestCase):
    def test_sender_identity_cannot_come_from_body(self):
        source=(ROOT/'tools/lemonades/userland/audit_probe.c').read_text()
        structs=source[source.index('struct audit_message {'):source.index('static int audit_fail(')]
        validator=source[source.index('static int valid_audit_message('):source.index('int check_audit_trailers(')]
        fixture=r'''
int main(int argc,char **argv) {
    if(argc!=2)return 2;int scenario=atoi(argv[1]);
    union audit_buffer buffer={0};struct audit_message *m=&buffer.message;
    m->header.msgh_size=sizeof(*m);m->header.msgh_id=0x39a0;m->header.msgh_local_port=700;m->sequence=1;
    m->claimed_identity.val[5]=900; /* body claims root parent; real sender is uid 501 */
    mach_msg_audit_trailer_t t={0};t.msgh_trailer_size=sizeof(t);
    t.msgh_audit.val[1]=501;t.msgh_audit.val[2]=501;t.msgh_audit.val[3]=501;t.msgh_audit.val[4]=501;
    t.msgh_audit.val[5]=901;t.msgh_audit.val[7]=23;
    switch(scenario){
        case 1:t.msgh_audit=m->claimed_identity;break;
        case 2:t.msgh_audit.val[5]=900;break;
        case 3:t.msgh_audit.val[1]=0;break;
        case 4:m->header.msgh_size=sizeof(m->header);break;
        case 5:t.msgh_trailer_type=1;break;
        case 6:t.msgh_trailer_size=0;break;
        case 7:t.msgh_audit.val[7]=0;break;
        case 8:m->sequence=0;break;
        case 9:m->header.msgh_bits=MACH_MSGH_BITS_COMPLEX;break;
        case 10:m->header.msgh_id=1;break;
        case 11:t.msgh_audit.val[2]=0;break;
        case 12:t.msgh_audit.val[3]=0;break;
        case 13:t.msgh_audit.val[4]=0;break;
        case 14:m->header.msgh_local_port=701;break;
        case 15:m->header.msgh_remote_port=702;break;
        case 16:m->claimed_identity.val[5]=901;break;
        case 17:t.msgh_audit.val[0]=0xffffffff;t.msgh_audit.val[6]=44;break;
    }
    memcpy(buffer.bytes+sizeof(*m),&t,sizeof(t));
    return valid_audit_message(&buffer,901,501,1,700)?0:1;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);c=tmp/'fixture.c';exe=tmp/'fixture'
            c.write_text('#include <mach/mach.h>\n#include <stdint.h>\n#include <string.h>\n#include <stdlib.h>\n'+structs+validator+fixture)
            result=subprocess.run(['xcrun','clang','-Werror',str(c),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            for scenario in range(18):
                with self.subTest(scenario=scenario):
                    result=subprocess.run([str(exe),str(scenario)],capture_output=True,text=True,timeout=5)
                    self.assertEqual(result.returncode,0 if scenario in (0,17) else 1,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
