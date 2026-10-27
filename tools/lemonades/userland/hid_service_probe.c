/* Isolated synthetic HID lifecycle test. No physical device, Apple binary
 * patch, entitlement override, or persistent input service. Pinned 20F66 ABI.
 * Callback contexts live until process exit, including on failed cleanup. */
#include "hid_touch_event.h"
#include <dispatch/dispatch.h>
#include <mach/mach_time.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <math.h>
#ifdef CHECK_INPUT_QUEUE
#include "hid_stream.h"
#include <sys/redwood_input.h>
#include <fcntl.h>
#endif

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
static CFDictionaryRef properties;
static atomic_bool opened;
static atomic_uint received,bad,resets;
static atomic_uint_fast64_t registry_id;
/* Only accessed on the observer's serial queue, set with dispatch_sync. */
static struct lemonades_hid_frame expected;
static unsigned observed;
static void server_reset(void *target,void *refcon,void *sender)
{
    (void)target;(void)refcon;(void)sender;
    atomic_store(&opened,false);atomic_fetch_add(&resets,1);
}
static void notification(void *target,void *refcon,Service service,uint32_t type,CFDictionaryRef value)
{
    (void)target;(void)refcon;(void)service;(void)value;
    printf("HID SERVICE notification=%u\n",type);fflush(stdout);
}
static CFTypeRef copy_property(void *target,void *refcon,Service service,CFStringRef key)
{
    (void)target;(void)refcon;(void)service;
    CFTypeRef value=key?CFDictionaryGetValue(properties,key):NULL;
    return value?CFRetain(value):NULL;
}
static Boolean set_property(void *target,void *refcon,Service service,CFStringRef key,CFTypeRef value)
{
    (void)target;(void)refcon;(void)service;
    char name[128]="?";
    if(key)CFStringGetCString(key,name,sizeof(name),kCFStringEncodingUTF8);
    printf("HID SERVICE set-property=%s\n",name);fflush(stdout);
    if(key && value && CFEqual(key,CFSTR("DeviceOpenedByEventSystem")) && CFGetTypeID(value)==CFBooleanGetTypeID()){
        atomic_store(&opened,CFBooleanGetValue(value));return true;
    }
    /* This diagnostic has no controller power/configuration implementation. */
    return false;
}
static const struct callbacks_v2 callbacks={.version=2,.notification=notification,
    .set_property=set_property,.copy_property=copy_property};
static void event_received(void *target,void *refcon,void *sender,IOHIDEventRef event)
{
    (void)target;(void)refcon;(void)sender;
    if(!event || IOHIDEventGetSenderID(event)!=atomic_load(&registry_id) ||
       IOHIDEventGetType(event)!=11 || IOHIDEventGetTimeStamp(event)!=expected.time)return;
    CFArrayRef children=IOHIDEventGetChildren(event);
    int good=children && CFArrayGetCount(children)==expected.count;
    if(good)for(unsigned i=0;i<expected.count;i++){
        IOHIDEventRef child=(IOHIDEventRef)CFArrayGetValueAtIndex(children,i);
        const struct lemonades_hid_finger *c=&expected.fingers[i];
        double x=IOHIDEventGetFloatValue(child,0xb0000),y=IOHIDEventGetFloatValue(child,0xb0001);
        good=good && IOHIDEventGetIntegerValue(child,0xb0005)==c->index &&
            IOHIDEventGetIntegerValue(child,0xb0006)==c->identity &&
            IOHIDEventGetIntegerValue(child,0xb0007)==c->mask &&
            IOHIDEventGetIntegerValue(child,0xb0008)==c->active &&
            IOHIDEventGetIntegerValue(child,0xb0009)==c->active &&
            isfinite(x) && isfinite(y) && fabs(x-c->x/65535.0)<0.0001 && fabs(y-c->y/65535.0)<0.0001;
    }
    if(!good){atomic_store(&bad,1);return;}
    if(!observed){observed=1;atomic_fetch_add(&received,1);}
}
static uint64_t service_id(Service service)
{
    CFNumberRef number=IOHIDServiceClientGetRegistryID(service);
    int64_t value=0;
    if(!number || CFGetTypeID(number)!=CFNumberGetTypeID() ||
       !CFNumberGetValue(number,kCFNumberSInt64Type,&value))return 0;
    return (uint64_t)value;
}
static void report_server(void)
{
    FILE *f=fopen("/private/var/mobile/Library/Logs/backboard-bringup.log","r");
    if(!f)return;
    char line[512];size_t count=0;
    while(count<65536 && fgets(line,sizeof(line),f)){
        count+=strlen(line);printf("HID SERVER LOG | %s",line);
    }
    fclose(f);
}
static int contains(Client observer,uint64_t id)
{
    CFArrayRef services=IOHIDEventSystemClientCopyServices(observer);
    if(!services)return -1; /* NULL is not proof of successful removal. */
    int found=0;
    if(CFGetTypeID(services)!=CFArrayGetTypeID()){CFRelease(services);return -1;}
    for(CFIndex i=0;i<CFArrayGetCount(services);i++)
        if(service_id((Service)CFArrayGetValueAtIndex(services,i))==id)found=1;
    CFRelease(services);return found;
}
static CFDictionaryRef make_properties(void)
{
    CFMutableDictionaryRef d=CFDictionaryCreateMutable(NULL,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    int page=13,usage=4;
    CFNumberRef p=CFNumberCreate(NULL,kCFNumberIntType,&page),u=CFNumberCreate(NULL,kCFNumberIntType,&usage);
    const void *keys[]={CFSTR("DeviceUsagePage"),CFSTR("DeviceUsage")};
    const void *values[]={p,u};
    CFDictionaryRef pair=NULL;CFArrayRef pairs=NULL;
    if(!d || !p || !u)goto fail;
    pair=CFDictionaryCreate(NULL,keys,values,2,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    if(!pair)goto fail;
    pairs=CFArrayCreate(NULL,(const void **)&pair,1,&kCFTypeArrayCallBacks);
    if(!pairs)goto fail;
    CFDictionarySetValue(d,CFSTR("PrimaryUsagePage"),p);CFDictionarySetValue(d,CFSTR("PrimaryUsage"),u);
    CFDictionarySetValue(d,keys[0],p);CFDictionarySetValue(d,keys[1],u);
    CFDictionarySetValue(d,CFSTR("DeviceUsagePairs"),pairs);
    CFDictionarySetValue(d,CFSTR("Product"),CFSTR("Lemonades SYNTHETIC HID test"));
    CFDictionarySetValue(d,CFSTR("Manufacturer"),CFSTR("HackiOS9r offline test"));
    CFDictionarySetValue(d,CFSTR("Transport"),CFSTR("Virtual"));
    CFDictionarySetValue(d,CFSTR("Built-In"),kCFBooleanFalse);
    CFDictionarySetValue(d,CFSTR("DisplayIntegrated"),kCFBooleanTrue);
    CFRelease(pairs);CFRelease(pair);CFRelease(p);CFRelease(u);return d;
fail:
    if(pairs)CFRelease(pairs);if(pair)CFRelease(pair);if(p)CFRelease(p);if(u)CFRelease(u);if(d)CFRelease(d);return NULL;
}
struct delivery { Service service; dispatch_queue_t observer_queue; };
static int deliver_frame(void *context,const struct lemonades_hid_frame *frame)
{
    struct delivery *d=context;
    unsigned before=atomic_load(&received);
    dispatch_sync(d->observer_queue,^{expected=*frame;observed=0;});
    IOHIDEventRef event=lemonades_hid_create_event(frame,0);
    if(!event)return 0;
    Boolean accepted=IOHIDVirtualServiceClientDispatchEvent(d->service,event);CFRelease(event);
    printf("HID SERVICE send step=%u accepted=%d\n",before,accepted);
    if(!accepted || atomic_load(&resets) || !atomic_load(&opened))return 0;
    for(unsigned i=0;i<30 && atomic_load(&received)==before && !atomic_load(&bad);i++)usleep(100000);
    return !atomic_load(&bad) && !atomic_load(&resets) && atomic_load(&received)==before+1;
}
int main(void)
{
    setbuf(stdout,NULL);puts("HID SERVICE BEGIN synthetic-lifecycle");
    int result=1;const char *failure="allocation";
    Client producer=NULL,observer=NULL;Service service=NULL;
    bool scheduled=false;
#ifdef CHECK_INPUT_QUEUE
    int input_fd=-1,input_writer=-1,input_down=0;
#endif
    dispatch_queue_t pq=dispatch_queue_create("lemonades.synthetic.provider",NULL);
    dispatch_queue_t oq=dispatch_queue_create("lemonades.synthetic.observer",NULL);
    properties=make_properties();
    if(!pq || !oq || !properties)goto finish;
    producer=IOHIDEventSystemClientCreateWithType(NULL,4,NULL);
    observer=IOHIDEventSystemClientCreateWithType(NULL,1,NULL);
    printf("HID SERVICE clients producer=%d observer=%d\n",producer!=NULL,observer!=NULL);
    if(!producer || !observer){failure="client creation";goto finish;}
    IOHIDEventSystemClientRegisterEventCallback(observer,event_received,NULL,NULL);
    IOHIDEventSystemClientRegisterResetCallback(observer,server_reset,NULL,NULL);
    IOHIDEventSystemClientRegisterResetCallback(producer,server_reset,NULL,NULL);
    IOHIDEventSystemClientScheduleWithDispatchQueue(observer,oq);
    IOHIDEventSystemClientScheduleWithDispatchQueue(producer,pq);scheduled=true;
    service=IOHIDVirtualServiceClientCreateWithCallbacks(producer,properties,&callbacks,NULL,NULL);
    printf("HID SERVICE created=%d\n",service!=NULL);
    if(!service){failure="registration";goto finish;}
    uint64_t id=service_id(service);atomic_store(&registry_id,id);
    printf("HID SERVICE registry-id=%llu\n",(unsigned long long)id);
    if(!id){failure="registry identity";goto finish;}
    for(unsigned i=0;i<80 && !atomic_load(&opened);i++)usleep(100000);
    if(!atomic_load(&opened) || atomic_load(&resets)){failure="open acknowledgement timeout";goto finish;}
    int visible=-1;
    for(unsigned i=0;i<30;i++){visible=contains(observer,id);if(visible==1)break;usleep(100000);}
    if(visible!=1){failure="observer enumeration";goto finish;}
    puts("HID SERVICE PASS synthetic-registration");
    struct delivery delivery={service,oq};
#ifdef CHECK_INPUT_QUEUE
    struct lemonades_hid_stream stream={0};
    struct lemonades_input_record snapshot;
    input_fd=open(LEMONADES_INPUT_DEVICE,O_RDONLY|O_NONBLOCK);
    input_writer=open(REDWOOD_TOUCH_DEVICE,O_WRONLY);
    if(input_fd<0 || input_writer<0 || read(input_fd,&snapshot,sizeof(snapshot))!=sizeof(snapshot) ||
       snapshot.active || snapshot.buttons || !(snapshot.flags&LEMONADES_INPUT_OPEN) ||
       lemonades_hid_consume(&stream,&snapshot,deliver_frame,&delivery)){
        failure="queue initial snapshot";goto finish;
    }
    for(unsigned step=0;step<3;step++){
        struct redwood_touch record={0,step+1,0,step?32768:1000,step?16384:2000};
        if(write(input_writer,&record,sizeof(record))!=sizeof(record)){failure="queue synthetic write";goto finish;}
        input_down=step!=2;
        if(read(input_fd,&snapshot,sizeof(snapshot))!=sizeof(snapshot) ||
           !(snapshot.flags&LEMONADES_INPUT_SYNTHETIC) ||
           lemonades_hid_consume(&stream,&snapshot,deliver_frame,&delivery)){
            failure="queue snapshot delivery";goto finish;
        }
    }
    if(atomic_load(&received)!=3){failure="queue delivery count";goto finish;}
    /* Lose an UP followed by a new DOWN in the same slot. Matching final masks
     * must not preserve the old HID identity or leave a stuck finger. */
    struct redwood_touch loss={0,REDWOOD_TOUCH_DOWN,0,500,500};
    if(write(input_writer,&loss,sizeof(loss))!=sizeof(loss)){failure="recovery down write";goto finish;}
    input_down=1;
    if(read(input_fd,&snapshot,sizeof(snapshot))!=sizeof(snapshot) ||
       lemonades_hid_consume(&stream,&snapshot,deliver_frame,&delivery)){failure="recovery down delivery";goto finish;}
    uint32_t old_identity=stream.touch.contacts[0].identity;
    loss.type=REDWOOD_TOUCH_UP;
    if(write(input_writer,&loss,sizeof(loss))!=sizeof(loss)){failure="lost up write";goto finish;}
    loss.type=REDWOOD_TOUCH_DOWN;
    if(write(input_writer,&loss,sizeof(loss))!=sizeof(loss)){failure="lost down write";goto finish;}
    loss.type=REDWOOD_TOUCH_MOVE;
    for(unsigned i=0;i<64;i++){
        loss.x=loss.y=600+i;
        if(write(input_writer,&loss,sizeof(loss))!=sizeof(loss)){failure="overflow move write";goto finish;}
    }
    if(read(input_fd,&snapshot,sizeof(snapshot))!=sizeof(snapshot) ||
       !(snapshot.flags&LEMONADES_INPUT_OVERFLOW) ||
       lemonades_hid_consume(&stream,&snapshot,deliver_frame,&delivery) ||
       stream.touch.contacts[0].identity<=old_identity){failure="HID overflow resynchronization";goto finish;}
    if(read(input_fd,&snapshot,sizeof(snapshot))!=sizeof(snapshot) || snapshot.x[0]!=663 ||
       lemonades_hid_consume(&stream,&snapshot,deliver_frame,&delivery)){failure="HID latest state";goto finish;}
    loss.type=REDWOOD_TOUCH_UP;
    if(write(input_writer,&loss,sizeof(loss))!=sizeof(loss)){failure="recovery final up write";goto finish;}
    input_down=0;
    if(read(input_fd,&snapshot,sizeof(snapshot))!=sizeof(snapshot) || snapshot.active ||
       lemonades_hid_consume(&stream,&snapshot,deliver_frame,&delivery) || atomic_load(&received)!=8){
        failure="HID recovery release/count";goto finish;
    }
    puts("HID SERVICE PASS synthetic-queue-recovery");
#else
    struct lemonades_hid_state state={0},next;
    struct lemonades_hid_frame frame;
    for(unsigned step=0;step<3;step++){
        if(lemonades_hid_prepare(&state,mach_absolute_time(),step+1,0,step?32768:1000,step?16384:2000,&next,&frame) ||
           !deliver_frame(&delivery,&frame)){failure="event delivery or field mismatch";goto finish;}
        state=next;
    }
#endif
    puts("HID SERVICE PASS synthetic-delivery");
#ifdef CHECK_INPUT_QUEUE
    puts("HID SERVICE PASS synthetic-queue-delivery");
#endif
    IOHIDVirtualServiceClientRemove(service);CFRelease(service);service=NULL;
    /* CopyServices returns NULL for an empty dictionary. Check the previously
     * visible identity has disappeared and a property RPC still succeeds. */
    extern Service IOHIDEventSystemClientCopyServiceForRegistryID(Client,uint64_t);
    int removed=0;
    for(unsigned i=0;i<30;i++){
        Service remaining=IOHIDEventSystemClientCopyServiceForRegistryID(observer,id);
        if(!remaining){removed=1;break;}CFRelease(remaining);usleep(100000);
    }
    CFTypeRef clients=IOHIDEventSystemClientCopyProperty(observer,CFSTR("ClientRecords"));
    int live=clients && CFGetTypeID(clients)==CFArrayGetTypeID() && CFArrayGetCount(clients)>0;
    if(clients)CFRelease(clients);
    if(!removed || !live || atomic_load(&resets)){failure="removal or live connection verification";goto finish;}
    puts("HID SERVICE PASS synthetic-removal");result=0;
finish:
#ifdef CHECK_INPUT_QUEUE
    if(input_down && input_writer>=0){
        struct redwood_touch release={0,REDWOOD_TOUCH_UP,0,0,0};
        (void)write(input_writer,&release,sizeof(release));
    }
    if(input_fd>=0)close(input_fd);if(input_writer>=0)close(input_writer);
#endif
    if(service){IOHIDVirtualServiceClientRemove(service);CFRelease(service);}
    if(observer && scheduled){IOHIDEventSystemClientUnregisterEventCallback(observer);IOHIDEventSystemClientUnscheduleFromDispatchQueue(observer,oq);}
    if(producer && scheduled)IOHIDEventSystemClientUnscheduleFromDispatchQueue(producer,pq);
    if(oq)dispatch_sync(oq,^{});if(pq)dispatch_sync(pq,^{});
    if(observer)CFRelease(observer);if(producer)CFRelease(producer);
    /* Keep callback properties/queues until exit; no lifetime assumption about
     * Apple's asynchronous cancellation internals is used to free contexts. */
    report_server();
    if(result)printf("HID SERVICE FAIL %s\n",failure);
    return result;
}
