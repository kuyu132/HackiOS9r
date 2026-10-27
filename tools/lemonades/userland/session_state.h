/* Read-only session consistency checks for the pinned usermanagerd diagnostic.
 * Key names come from original CFStrings; UID mask comes from XNU's
 * osfmk/arm/cpu_capabilities.h and the daemon's 0x100066bf4 helper. */
#import <Foundation/Foundation.h>
#include <mach/mach.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

#ifndef SESSION_STATE_PATH
#define SESSION_STATE_PATH "/private/var/keybags/usersession.kb"
#endif
#ifndef SESSION_STATE_OWNER
#define SESSION_STATE_OWNER 0
#endif

static BOOL session_uint(id value,uint32_t *number)
{
    if (![value isKindOfClass:[NSNumber class]] ||
        CFGetTypeID((__bridge CFTypeRef)value)==CFBooleanGetTypeID() ||
        CFNumberIsFloatType((__bridge CFNumberRef)value)) return NO;
    int64_t n=[value longLongValue];
    if (n<0 || n>0x3fffffff) return NO;
    *number=(uint32_t)n;return YES;
}

/* Walk only property-list containers, with explicit resource limits. Reject
 * duplicate session IDs, including IDs in non-foreground records. */
static BOOL collect_sessions(id value,NSMutableDictionary *sessions,unsigned depth,NSUInteger *budget)
{
    if (depth>16 || !*budget) return NO;
    --*budget;
    if ([value isKindOfClass:[NSDictionary class]]) {
        if ([value count]>256) return NO;
        id sessionID=value[@"MKBUserSessionID"];
        if (sessionID) {
            uint32_t uid;
            if (!session_uint(sessionID,&uid) || sessions[@(uid)]) return NO;
            sessions[@(uid)]=value;
        }
        for (id key in value) {
            if (![key isKindOfClass:[NSString class]] ||
                !collect_sessions(value[key],sessions,depth+1,budget)) return NO;
        }
    } else if ([value isKindOfClass:[NSArray class]]) {
        if ([value count]>256) return NO;
        for (id item in value) if (!collect_sessions(item,sessions,depth+1,budget)) return NO;
    } else if ([value isKindOfClass:[NSData class]] && [value length]>=8 &&
               !memcmp([value bytes],"bplist00",8)) {
        if ([value length]>1048576) return NO;
        id nested=[NSPropertyListSerialization propertyListWithData:value options:NSPropertyListImmutable format:NULL error:NULL];
        if (!nested || !collect_sessions(nested,sessions,depth+1,budget)) return NO;
    }
    return YES;
}

static BOOL validate_session_state(NSDictionary *attributes,id saved,uint32_t flags)
{
    if (![attributes isKindOfClass:[NSDictionary class]] ||
        ![saved isKindOfClass:[NSDictionary class]]) return NO;
    uint32_t uid;
    if (!session_uint(attributes[@"MKBUserSessionID"],&uid) || uid!=(flags&0x3fffffff)) return NO;
    id foreground=attributes[@"MKBUserSessionForeground"];
    if (!foreground || CFGetTypeID((__bridge CFTypeRef)foreground)!=CFBooleanGetTypeID() ||
        ![foreground boolValue]) return NO;
    NSMutableDictionary *sessions=[NSMutableDictionary dictionary];NSUInteger budget=4096;
    if (!collect_sessions(saved,sessions,0,&budget) || !sessions.count) return NO;
    NSUInteger foregroundCount=0;
    for (NSNumber *sessionID in sessions) {
        id flag=sessions[sessionID][@"MKBUserSessionForeground"];
        if (!flag || CFGetTypeID((__bridge CFTypeRef)flag)!=CFBooleanGetTypeID()) return NO;
        if ([flag boolValue]) ++foregroundCount;
    }
    if (foregroundCount!=1 || ![attributes isEqualToDictionary:sessions[@(uid)]]) return NO;
    printf("NSXPC session consistency uid=%u saved-count=%lu attributes=%lu\n",
           uid,(unsigned long)sessions.count,(unsigned long)attributes.count);
    return YES;
}

static BOOL check_session_state(NSDictionary *attributes)
{
    int fd=open(SESSION_STATE_PATH,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);struct stat st;
    if (fd<0) return NO;
    if (fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=SESSION_STATE_OWNER ||
        (st.st_mode&0022) || st.st_size<=0 || st.st_size>1048576) {close(fd);return NO;}
    NSMutableData *data=[NSMutableData dataWithLength:(NSUInteger)st.st_size];size_t offset=0;
    while (offset<data.length) {
        ssize_t got=read(fd,(char *)data.mutableBytes+offset,data.length-offset);
        if (got<0 && errno==EINTR) continue;
        if (got<=0) {close(fd);return NO;}
        offset+=(size_t)got;
    }
    char extra;ssize_t got;
    do {got=read(fd,&extra,1);} while (got<0 && errno==EINTR);
    close(fd);if (got!=0) return NO;
    id saved=[NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:NULL error:NULL];
    uint32_t flags=0;mach_port_t host=mach_host_self();
    kern_return_t result=host_get_multiuser_config_flags(host,&flags);
    mach_port_deallocate(mach_task_self(),host);
    if (result!=KERN_SUCCESS) return NO;
    BOOL valid=validate_session_state(attributes,saved,flags);
    if (!valid) {
        /* Generated guest state only: show shape and numeric identity, not blobs. */
        printf("NSXPC session mismatch flags=0x%x\n",flags);
        NSLog(@"Session attribute keys: %@; saved top-level keys: %@",attributes.allKeys,
              [saved isKindOfClass:[NSDictionary class]]?[saved allKeys]:@[]);
    }
    return valid;
}
