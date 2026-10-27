"""Validate reply handling with local XPC objects; never contact a host service."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(sys.platform=='darwin','requires host XPC object library')
class MuserReplyTests(unittest.TestCase):
    def test_mode_aware_reply_validation(self):
        source=(ROOT/'tools/lemonades/userland/muser_probe.c').read_text()
        fixture=r'''
extern void xpc_dictionary_set_bool(xpc_object_t,const char *,bool);
extern void xpc_dictionary_set_value(xpc_object_t,const char *,xpc_object_t);
extern xpc_object_t xpc_array_create(const xpc_object_t *,size_t);
extern void xpc_array_set_string(xpc_object_t,size_t,const char *);
static int scenario,request_number;
kern_return_t host_get_multiuser_config_flags(host_t h,uint32_t *flags) {
    (void)h;*flags=scenario==1 ? 0x800001f5 : 501;return KERN_SUCCESS;
}
xpc_object_t xpc_pipe_create(const char *name,uint64_t flags) {
    (void)name;(void)flags;return xpc_dictionary_create(NULL,NULL,0);
}
int xpc_pipe_routine(xpc_object_t pipe,xpc_object_t request,xpc_object_t *reply) {
    (void)pipe;(void)request;
    if(scenario==6)return 32;
    *reply=xpc_dictionary_create(NULL,NULL,0);
    if(request_number++==0) {
        if(scenario==3)xpc_dictionary_set_int64(*reply,"available",1);
        else xpc_dictionary_set_bool(*reply,"available",true);
    } else if(request_number==2) {
        if(scenario==2 || scenario==7) {
            xpc_dictionary_set_int64(*reply,"pw_uid",scenario==7?0:501);
            xpc_dictionary_set_int64(*reply,"pw_gid",501);
            xpc_dictionary_set_string(*reply,"pw_name","mobile");
            xpc_dictionary_set_string(*reply,"pw_dir","/var/mobile");
        }
    } else {
        xpc_dictionary_set_int64(*reply,"gr_gid",scenario==4?0:299);
        xpc_dictionary_set_string(*reply,"gr_name","systemusers");
        xpc_object_t members=xpc_array_create(NULL,0);
        if(scenario!=5)xpc_array_set_string(members,(size_t)-1,"root");
        xpc_dictionary_set_value(*reply,"gr_members",members);xpc_release(members);
    }
    return 0;
}
int main(int argc,char **argv) {if(argc!=2)return 2;scenario=atoi(argv[1]);return muser_probe_child();}
'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);c=tmp/'muser.c';c.write_text(source+fixture)
            subprocess.run(['xcrun','clang','-Werror',str(c),'-o',str(tmp/'muser')],check=True,capture_output=True)
            for scenario,expected in enumerate([0,1,0,1,1,1,1,1]):
                with self.subTest(scenario=scenario):
                    result=subprocess.run([str(tmp/'muser'),str(scenario)],capture_output=True,text=True)
                    self.assertEqual(result.returncode,expected,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
