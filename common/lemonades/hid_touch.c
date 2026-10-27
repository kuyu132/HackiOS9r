#include "hid_touch.h"
#include <stddef.h>
#include <string.h>
static int valid(const struct lemonades_hid_state *s)
{
    for(unsigned i=0;i<LEMONADES_HID_CONTACTS;i++){
        const struct lemonades_hid_contact *c=&s->contacts[i];
        if(c->active>1 || c->x>65535 || c->y>65535 || c->identity>s->last_identity ||
           (c->active && !c->identity))return 0;
        for(unsigned j=0;c->active && j<i;j++)
            if(s->contacts[j].active && s->contacts[j].identity==c->identity)return 0;
    }
    return 1;
}
int lemonades_hid_prepare(const struct lemonades_hid_state *s,
    uint64_t time, uint32_t type, uint32_t finger, uint32_t x, uint32_t y,
    struct lemonades_hid_state *next, struct lemonades_hid_frame *out)
{
    if(!s || !next || !out || s==next || (const void *)s==(void *)out ||
       (void *)next==(void *)out || !valid(s) || finger>=LEMONADES_HID_CONTACTS ||
       type<1 || type>3 || x>65535 || y>65535)return LEMONADES_HID_INVALID;
    if(time<s->time || (type==1 ? s->contacts[finger].active : !s->contacts[finger].active))
        return LEMONADES_HID_SEQUENCE;
    if(type==1 && s->last_identity==UINT32_MAX)return LEMONADES_HID_ID_EXHAUSTED;
    struct lemonades_hid_state n=*s;
    struct lemonades_hid_frame f={0};
    struct lemonades_hid_contact *c=&n.contacts[finger];
    n.time=time;c->x=x;c->y=y;c->active=type!=3;
    if(type==1)c->identity=++n.last_identity;
    uint32_t mask=type==2 ? LEMONADES_HID_POSITION : LEMONADES_HID_RANGE|LEMONADES_HID_TOUCH;
    f.time=time;f.x=x;f.y=y;f.mask=mask&~LEMONADES_HID_RANGE;
    for(unsigned i=0;i<LEMONADES_HID_CONTACTS;i++){
        c=&n.contacts[i];
        if(!c->active && i!=finger)continue;
        f.fingers[f.count++]=(struct lemonades_hid_finger){i+1,c->identity,c->x,c->y,i==finger?mask:0,c->active};
        f.active|=c->active;
    }
    *next=n;*out=f;return LEMONADES_HID_OK;
}
int lemonades_hid_release_all(const struct lemonades_hid_state *s,uint64_t time,
    struct lemonades_hid_state *next,struct lemonades_hid_frame *out)
{
    if(!s || !next || !out || s==next || (const void *)s==(void *)out ||
       (void *)next==(void *)out || !valid(s))return LEMONADES_HID_INVALID;
    if(time<s->time)return LEMONADES_HID_SEQUENCE;
    struct lemonades_hid_state n=*s;
    struct lemonades_hid_frame f={0};n.time=time;f.time=time;
    for(unsigned i=0;i<LEMONADES_HID_CONTACTS;i++){
        const struct lemonades_hid_contact *c=&s->contacts[i];
        if(!c->active)continue;
        f.fingers[f.count++]=(struct lemonades_hid_finger){i+1,c->identity,c->x,c->y,LEMONADES_HID_RANGE|LEMONADES_HID_TOUCH,0};
        f.x=c->x;f.y=c->y;n.contacts[i].active=0;
    }
    if(f.count)f.mask=LEMONADES_HID_TOUCH;
    *next=n;*out=f;return LEMONADES_HID_OK;
}
