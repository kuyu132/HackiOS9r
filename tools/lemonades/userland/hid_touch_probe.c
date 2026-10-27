/* Synthetic record encoding only. Never publishes a HID device or sends events. */
#include "hid_touch_event.h"
#include <sys/redwood_input.h>
#include <stddef.h>
#include <stdio.h>
#include <math.h>
extern uint32_t IOHIDEventGetType(IOHIDEventRef);
extern uint64_t IOHIDEventGetTimeStamp(IOHIDEventRef);
extern CFArrayRef IOHIDEventGetChildren(IOHIDEventRef);
extern CFIndex IOHIDEventGetIntegerValue(IOHIDEventRef,uint32_t);
extern double IOHIDEventGetFloatValue(IOHIDEventRef,uint32_t);
_Static_assert(sizeof(struct redwood_touch)==24,"queue record size");
_Static_assert(offsetof(struct redwood_touch,type)==8 && offsetof(struct redwood_touch,x)==16,"queue record offsets");
static int check(const struct lemonades_hid_frame *f,unsigned built_in)
{
    if(lemonades_hid_create_event(f,2)){puts("HID TOUCH FAIL invalid device profile");return 0;}
    IOHIDEventRef event=lemonades_hid_create_event(f,built_in);
    if(!event){puts("HID TOUCH FAIL event allocation");return 0;}
    CFArrayRef children=IOHIDEventGetChildren(event);
    int good=IOHIDEventGetType(event)==11 && IOHIDEventGetTimeStamp(event)==f->time &&
        children && CFArrayGetCount(children)==f->count &&
        IOHIDEventGetIntegerValue(event,4)==built_in;
    if(good)for(unsigned i=0;i<f->count;i++){
        IOHIDEventRef child=(IOHIDEventRef)CFArrayGetValueAtIndex(children,i);
        const struct lemonades_hid_finger *c=&f->fingers[i];
        CFIndex index=IOHIDEventGetIntegerValue(child,0xb0005),identity=IOHIDEventGetIntegerValue(child,0xb0006);
        CFIndex mask=IOHIDEventGetIntegerValue(child,0xb0007),range=IOHIDEventGetIntegerValue(child,0xb0008);
        CFIndex touch=IOHIDEventGetIntegerValue(child,0xb0009);
        double x=IOHIDEventGetFloatValue(child,0xb0000),y=IOHIDEventGetFloatValue(child,0xb0001);
        printf("HID TOUCH child index=%ld identity=%ld mask=%ld range=%ld touch=%ld x=%.6f y=%.6f\n",
            (long)index,(long)identity,(long)mask,(long)range,(long)touch,x,y);
        good=good && IOHIDEventGetType(child)==11 && IOHIDEventGetTimeStamp(child)==f->time &&
            IOHIDEventGetIntegerValue(child,4)==built_in && index==c->index && identity==c->identity && mask==c->mask && range==c->active && touch==c->active &&
            isfinite(x) && isfinite(y) && fabs(x-c->x/65535.0)<0.0001 && fabs(y-c->y/65535.0)<0.0001;
    }
    CFRelease(event);
    if(!good)puts("HID TOUCH FAIL original event fields");
    return good;
}
int main(void)
{
    puts("HID TOUCH BEGIN synthetic-encoding");fflush(stdout);
    struct lemonades_hid_state s={0},next;
    struct lemonades_hid_frame frame;
    const struct redwood_touch records[]={
        {100,REDWOOD_TOUCH_DOWN,0,0,65535},
        {101,REDWOOD_TOUCH_DOWN,9,65535,0},
        {102,REDWOOD_TOUCH_MOVE,0,32768,16384},
        {103,REDWOOD_TOUCH_UP,0,32768,16384},
        {104,REDWOOD_TOUCH_DOWN,0,1,2}
    };
    for(unsigned i=0;i<sizeof(records)/sizeof(records[0]);i++){
        const struct redwood_touch *r=&records[i];
        if(lemonades_hid_prepare(&s,r->time,r->type,r->finger,r->x,r->y,&next,&frame) || (!check(&frame,0) || !check(&frame,1)))return 1;
        s=next;
    }
    if(lemonades_hid_release_all(&s,105,&next,&frame) || (!check(&frame,0) || !check(&frame,1)))return 1;
    s=next;
    if(lemonades_hid_release_all(&s,106,&next,&frame) || frame.count || lemonades_hid_create_event(&frame,0)){
        puts("HID TOUCH FAIL empty release");return 1;
    }
    puts("HID TOUCH PASS device-profile-encoding");
    puts("HID TOUCH PASS event-encoding");fflush(stdout);return 0;
}
