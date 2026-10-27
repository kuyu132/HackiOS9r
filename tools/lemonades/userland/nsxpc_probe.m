/* Read-only request to original UMSyncService. Selector/reply ABI and the EPERM
 * branch are evidenced in the pinned usermanagerd's ObjC metadata/disassembly. */
#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>
#include <stdio.h>
#include <unistd.h>
#include <errno.h>
#include "session_state.h"

/* The pinned iOS daemon uses this selector, although the public iOS SDK marks
 * the macOS-facing declaration unavailable. Keep the private ABI local to this
 * diagnostic instead of changing SDK availability or Foundation headers. */
@protocol BringupMachConnection
- (instancetype)initWithMachServiceName:(NSString *)name options:(NSUInteger)options;
@end

@protocol BringupUserManagementProtocol
- (void)fetchPersonaListforPid:(int)pid withCompletionHandler:(void (^)(NSArray *,NSError *))reply;
- (void)foregroundUserSessionAttributesWithReply:(void (^)(NSDictionary *,NSError *))reply;
@end

static int foreground_session(NSXPCConnection *connection)
{
    puts("NSXPC BEGIN foreground-session");fflush(stdout);
    dispatch_semaphore_t done=dispatch_semaphore_create(0);
    __block int outcome=1;
    id<BringupUserManagementProtocol> proxy=[connection remoteObjectProxyWithErrorHandler:^(NSError *error) {
        printf("NSXPC FAIL foreground transport domain=%s code=%ld\n",error.domain.UTF8String,(long)error.code);
        dispatch_semaphore_signal(done);
    }];
    [proxy foregroundUserSessionAttributesWithReply:^(NSDictionary *attributes,NSError *error) {
        printf("NSXPC foreground reply domain=%s code=%ld data=%d\n",
            error ? error.domain.UTF8String : "none",(long)error.code,attributes!=nil);
        if (!error && [attributes isKindOfClass:[NSDictionary class]] && attributes.count) {
            printf("NSXPC foreground attribute-count=%lu\n",(unsigned long)attributes.count);
            if (check_session_state(attributes)) {
                outcome=0;puts("NSXPC PASS foreground-session");
                puts("NSXPC PASS session-state-kernel");
            } else puts("NSXPC FAIL foreground state mismatch");
        } else puts("NSXPC FAIL foreground session unavailable");
        dispatch_semaphore_signal(done);
    }];
    if (dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC))) {
        puts("NSXPC FAIL foreground response timeout");return 1;
    }
    return outcome;
}

int main(void)
{
    @autoreleasepool {
        puts("NSXPC BEGIN persona-query");fflush(stdout);
        NSXPCConnection *connection=(NSXPCConnection *)[(id<BringupMachConnection>)[NSXPCConnection alloc]
            initWithMachServiceName:@"com.apple.mobile.usermanagerd.xpc" options:0];
        connection.remoteObjectInterface=[NSXPCInterface interfaceWithProtocol:@protocol(BringupUserManagementProtocol)];
        [connection resume];
        dispatch_semaphore_t done=dispatch_semaphore_create(0);
        __block int outcome=1;
        id<BringupUserManagementProtocol> proxy=[connection remoteObjectProxyWithErrorHandler:^(NSError *error) {
            printf("NSXPC FAIL transport domain=%s code=%ld\n",error.domain.UTF8String,(long)error.code);
            dispatch_semaphore_signal(done);
        }];
        [proxy fetchPersonaListforPid:getpid() withCompletionHandler:^(NSArray *personas,NSError *error) {
            printf("NSXPC persona reply domain=%s code=%ld data=%d\n",
                error ? error.domain.UTF8String : "none",(long)error.code,personas!=nil);
            /* No persona-fetch entitlement is embedded in this test executable. */
            if (!personas && [error.domain isEqualToString:NSPOSIXErrorDomain] && error.code==EPERM) {
                outcome=0;puts("NSXPC PASS persona-fetch-denied");
            } else puts("NSXPC FAIL unexpected persona response");
            dispatch_semaphore_signal(done);
        }];
        if (dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC))) {
            puts("NSXPC FAIL response timeout");outcome=1;
        }
        if (!outcome) outcome=foreground_session(connection);
        [connection invalidate];fflush(stdout);return outcome;
    }
}
