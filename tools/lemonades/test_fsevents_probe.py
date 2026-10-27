"""Test callback acceptance with local arrays; never create a host event stream."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform=='darwin','requires host CoreServices')
class FSEventsCallbackTests(unittest.TestCase):
    def test_path_flags_and_id_are_required(self):
        source=(ROOT/'tools/lemonades/userland/fsevents_probe.c').read_text()
        fixture=r'''
#undef main
int main(int argc,char **argv) {
    if(argc!=2)return 2;int scenario=atoi(argv[1]);
    struct observation seen={0};strcpy(seen.file,"/fixture/created");
    seen.done=dispatch_semaphore_create(0);
    char *path=scenario==1?"/fixture/unrelated":seen.file;
    uint32_t flags=scenario==2?0x1010:(scenario==3?0x100:0x10100);
    if(scenario>=4 && scenario<=7)flags|=1u<<(scenario-4);
    uint64_t id=scenario==8?0:(scenario==9?UINT64_MAX:123);
    if(scenario>=11){
        seen.cfpaths=1;seen.required=0x20200;
        CFTypeRef value=scenario==13?(CFTypeRef)kCFBooleanTrue:(CFTypeRef)CFSTR("/fixture/created");
        CFArrayRef values=CFArrayCreate(NULL,&value,scenario==14?0:1,&kCFTypeArrayCallBacks);
        flags=scenario==12?0x10200:0x20200;
        if(scenario==15)flags|=4;
        if(scenario>=16){
            seen.required=0x20100;seen.id=1;seen.flags=0x20100;
            dispatch_semaphore_signal(seen.done);dispatch_semaphore_signal(seen.done);
            expect_directory_deletion(&seen);
            if(seen.id || seen.flags || seen.required!=0x20200 || dispatch_semaphore_wait(seen.done,DISPATCH_TIME_NOW)==0)return 3;
            if(scenario==17)flags=0x20100;
        }
        received(NULL,&seen,1,(void *)values,&flags,&id);CFRelease(values);
    }else received(NULL,&seen,scenario==10?0:1,&path,&flags,&id);
    int valid=dispatch_semaphore_wait(seen.done,DISPATCH_TIME_NOW)==0 && seen.id==123;
    dispatch_release(seen.done);return valid?0:1;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);path=tmp/'fixture.c';path.write_text('#define main diagnostic_main\n'+source+fixture)
            result=subprocess.run(['xcrun','clang','-Werror',str(path),'-framework','CoreFoundation',
                                   '-framework','CoreServices','-o',str(tmp/'fixture')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            for scenario in range(18):
                with self.subTest(scenario=scenario):
                    result=subprocess.run([str(tmp/'fixture'),str(scenario)],capture_output=True,text=True,timeout=5)
                    self.assertEqual(result.returncode,0 if scenario in (0,11,16) else 1,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
