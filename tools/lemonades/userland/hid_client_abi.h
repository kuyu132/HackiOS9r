/* Private ABI verified against pinned iOS 16.5 / 20F66; see HID touch audit. */
#ifndef LEMONADES_HID_CLIENT_ABI_H
#define LEMONADES_HID_CLIENT_ABI_H
#include "hid_touch_event.h"
#include <dispatch/dispatch.h>
#include <stddef.h>
typedef struct __IOHIDEventSystemClient *Client;
typedef struct __IOHIDServiceClient *Service;
struct callbacks_v2 {
    uint64_t version;
    void (*notification)(void *,void *,Service,uint32_t,CFDictionaryRef);
    Boolean (*set_property)(void *,void *,Service,CFStringRef,CFTypeRef);
    CFTypeRef (*copy_property)(void *,void *,Service,CFStringRef);
    IOHIDEventRef (*copy_event)(void *,void *,Service,uint32_t,IOHIDEventRef,uint32_t);
    int (*set_output)(void *,void *,Service,IOHIDEventRef);
    CFTypeRef (*copy_matching)(void *,void *,Service,CFDictionaryRef);
};
_Static_assert(sizeof(struct callbacks_v2)==56 && offsetof(struct callbacks_v2,copy_property)==24,"20F66 callback ABI");
extern Client IOHIDEventSystemClientCreateWithType(CFAllocatorRef,int,CFDictionaryRef);
extern void IOHIDEventSystemClientScheduleWithDispatchQueue(Client,dispatch_queue_t);
extern void IOHIDEventSystemClientUnscheduleFromDispatchQueue(Client,dispatch_queue_t);
extern void IOHIDEventSystemClientRegisterEventCallback(Client,void (*)(void *,void *,void *,IOHIDEventRef),void *,void *);
extern void IOHIDEventSystemClientUnregisterEventCallback(Client);
extern CFArrayRef IOHIDEventSystemClientCopyServices(Client);
extern void IOHIDEventSystemClientRegisterResetCallback(Client,void (*)(void *,void *,void *),void *,void *);
extern CFTypeRef IOHIDEventSystemClientCopyProperty(Client,CFStringRef);
extern Service IOHIDVirtualServiceClientCreateWithCallbacks(Client,CFDictionaryRef,const struct callbacks_v2 *,void *,void *);
/* Remove has no Boolean result in the pinned binary. Verify disappearance. */
extern void IOHIDVirtualServiceClientRemove(Service);
extern Boolean IOHIDVirtualServiceClientDispatchEvent(Service,IOHIDEventRef);
extern CFNumberRef IOHIDServiceClientGetRegistryID(Service);
extern uint64_t IOHIDEventGetSenderID(IOHIDEventRef);
extern uint64_t IOHIDEventGetTimeStamp(IOHIDEventRef);
extern uint32_t IOHIDEventGetType(IOHIDEventRef);
extern CFArrayRef IOHIDEventGetChildren(IOHIDEventRef);
extern CFIndex IOHIDEventGetIntegerValue(IOHIDEventRef,uint32_t);
extern double IOHIDEventGetFloatValue(IOHIDEventRef,uint32_t);
extern Service IOHIDEventSystemClientCopyServiceForRegistryID(Client,uint64_t);
extern CFTypeRef IOHIDServiceClientCopyProperty(Service,CFStringRef);
CFDictionaryRef lemonades_hid_properties(CFStringRef product,unsigned built_in);
uint64_t lemonades_hid_service_id(Service service);
#endif
