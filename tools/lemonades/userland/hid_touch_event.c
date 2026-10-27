/* iOS 16.5 IOKit ABI; no library interposition or Apple binary patch.
 * No edge-gesture or pressure measurements are invented. Contact pressure is a
 * binary contact indicator until the controller's pressure data is integrated.
 */
#include "hid_touch_event.h"
extern IOHIDEventRef IOHIDEventCreateDigitizerEvent(CFAllocatorRef,uint64_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,double,double,double,double,double,double,Boolean,Boolean,uint32_t);
extern IOHIDEventRef IOHIDEventCreateDigitizerFingerEvent(CFAllocatorRef,uint64_t,uint32_t,uint32_t,uint32_t,double,double,double,double,double,Boolean,Boolean,uint32_t);
extern void IOHIDEventSetIntegerValue(IOHIDEventRef,uint32_t,CFIndex);
extern void IOHIDEventAppendEvent(IOHIDEventRef,IOHIDEventRef,uint32_t);
IOHIDEventRef lemonades_hid_create_event(const struct lemonades_hid_frame *f,unsigned built_in)
{
    if(built_in>1 || !f || !f->count || f->count>LEMONADES_HID_CONTACTS || f->x>65535 || f->y>65535 ||
       f->active>1 || (f->mask&~6u))return NULL;
    unsigned active=0;uint32_t last=0;
    for(unsigned i=0;i<f->count;i++){
        const struct lemonades_hid_finger *c=&f->fingers[i];
        if(c->index<=last || c->index>LEMONADES_HID_CONTACTS || !c->identity ||
           c->x>65535 || c->y>65535 || c->active>1 || (c->mask&~7u))return NULL;
        for(unsigned j=0;j<i;j++)if(f->fingers[j].identity==c->identity)return NULL;
        last=c->index;active|=c->active;
    }
    if(active!=f->active)return NULL;
    IOHIDEventRef hand=IOHIDEventCreateDigitizerEvent(NULL,f->time,3,0,0,f->mask,0,
        f->x/65535.0,f->y/65535.0,0,0,0,0,f->active,f->active,0);
    if(!hand)return NULL;
    IOHIDEventSetIntegerValue(hand,0xb0019,1); /* DisplayIntegrated, pinned upstream ABI */
    IOHIDEventSetIntegerValue(hand,4,built_in);       /* IsBuiltIn */
    for(unsigned i=0;i<f->count;i++){
        const struct lemonades_hid_finger *c=&f->fingers[i];
        IOHIDEventRef finger=IOHIDEventCreateDigitizerFingerEvent(NULL,f->time,c->index,c->identity,c->mask,
            c->x/65535.0,c->y/65535.0,0,c->active?1.0:0.0,0,c->active,c->active,0);
        if(!finger){CFRelease(hand);return NULL;}
        IOHIDEventSetIntegerValue(finger,0xb0019,1);
        IOHIDEventSetIntegerValue(finger,4,built_in);
        IOHIDEventAppendEvent(hand,finger,0);CFRelease(finger);
    }
    return hand;
}
