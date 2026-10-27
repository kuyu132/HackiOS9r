"""Exercise the actual probe with in-process reply fixtures, without host IPC."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform=='darwin','requires host Foundation')
class NSXPCReplyTests(unittest.TestCase):
    def test_denial_and_session_reply_validation(self):
        source=(ROOT/'tools/lemonades/userland/nsxpc_probe.m').read_text()
        prefix=r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <unistd.h>
#include <errno.h>
static int scenario;
@interface FixtureConnection : NSObject
@property(strong) NSXPCInterface *remoteObjectInterface;
@property(copy) void (^errorHandler)(NSError *);
- (instancetype)initWithMachServiceName:(NSString *)name options:(NSUInteger)options;
- (void)resume;
- (void)invalidate;
- (id)remoteObjectProxyWithErrorHandler:(void (^)(NSError *))handler;
@end
#define NSXPCConnection FixtureConnection
#define main diagnostic_main
'''
        suffix=r'''
#undef main
#undef NSXPCConnection
kern_return_t host_get_multiuser_config_flags(host_t host,uint32_t *flags) {
    (void)host;*flags=501;return KERN_SUCCESS;
}
@implementation FixtureConnection
- (instancetype)initWithMachServiceName:(NSString *)name options:(NSUInteger)options {
    assert([name isEqualToString:@"com.apple.mobile.usermanagerd.xpc"] && options==0);
    return [super init];
}
- (void)resume {}
- (void)invalidate {}
- (id)remoteObjectProxyWithErrorHandler:(void (^)(NSError *))handler {
    self.errorHandler=handler;return self;
}
- (void)fetchPersonaListforPid:(int)pid withCompletionHandler:(void (^)(NSArray *,NSError *))reply {
    assert(pid==getpid());
    if (scenario==6) {self.errorHandler([NSError errorWithDomain:NSCocoaErrorDomain code:4097 userInfo:nil]);return;}
    NSError *error=[NSError errorWithDomain:scenario==1?NSCocoaErrorDomain:NSPOSIXErrorDomain
                                       code:scenario==2?EINVAL:EPERM userInfo:nil];
    if (scenario==5) error=nil;
    reply(scenario==3?@[@1]:(scenario==4?@[]:nil),error);
}
- (void)foregroundUserSessionAttributesWithReply:(void (^)(NSDictionary *,NSError *))reply {
    if (scenario==11) {self.errorHandler([NSError errorWithDomain:NSCocoaErrorDomain code:4097 userInfo:nil]);return;}
    id data=@{@"MKBUserSessionID":@501,@"MKBUserSessionForeground":@YES};
    if (scenario==7) data=nil;
    if (scenario==8) data=@{};
    if (scenario==9) data=@"not a dictionary";
    NSError *error=nil;
    if (scenario==10 || scenario==12) error=[NSError errorWithDomain:NSPOSIXErrorDomain code:EINVAL userInfo:nil];
    if (scenario==10) data=nil;
    reply(data,error);
}
@end
int main(int argc,char **argv) {
    if(argc!=2)return 2;scenario=atoi(argv[1]);return diagnostic_main();
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);fixture=tmp/'fixture.m';fixture.write_text(prefix+source+suffix)
            (tmp/'session_state.h').write_text((ROOT/'tools/lemonades/userland/session_state.h').read_text())
            state=tmp/'usersession.kb'
            state.write_bytes(plistlib.dumps({'sessions':[{'MKBUserSessionID':501,'MKBUserSessionForeground':True}]}))
            executable=tmp/'probe'
            result=subprocess.run(['xcrun','clang','-fobjc-arc','-fblocks','-Werror',str(fixture),
                                   '-DSESSION_STATE_PATH="'+str(state)+'"','-DSESSION_STATE_OWNER=getuid()',
                                   '-framework','Foundation','-o',str(executable)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            for scenario in range(13):
                with self.subTest(scenario=scenario):
                    result=subprocess.run([str(executable),str(scenario)],capture_output=True,text=True,timeout=5)
                    self.assertEqual(result.returncode,0 if scenario==0 else 1,result.stdout+result.stderr)
                    if scenario:
                        self.assertIn('NSXPC FAIL ',result.stdout)
                    else:
                        self.assertIn('NSXPC PASS persona-fetch-denied',result.stdout)
                        self.assertIn('NSXPC PASS foreground-session',result.stdout)


if __name__=='__main__':unittest.main()
