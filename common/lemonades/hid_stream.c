#include "hid_stream.h"
static int submit(struct lemonades_hid_stream *s,const struct lemonades_hid_state *next,
    const struct lemonades_hid_frame *frame,lemonades_hid_sink sink,void *context)
{
    if(frame->count && !sink(context,frame)){s->poisoned=1;return -2;}
    s->touch=*next;return 0;
}
int lemonades_hid_consume(struct lemonades_hid_stream *s,const struct lemonades_input_record *r,
    lemonades_hid_sink sink,void *context)
{
    if(!s || !r || !sink)return -1;
    if(s->poisoned)return -2;
    if(r->version!=LEMONADES_INPUT_VERSION || !r->sequence || r->active>>LEMONADES_INPUT_CONTACTS ||
       r->buttons>15 || r->flags&~LEMONADES_INPUT_FLAGS || r->time<s->touch.time ||
       (s->seen && (r->sequence<=s->sequence || r->dropped<s->dropped)))return -1;
    for(unsigned i=0;i<LEMONADES_INPUT_CONTACTS;i++)if(r->x[i]>65535 || r->y[i]>65535)return -1;
    struct lemonades_hid_state next;
    struct lemonades_hid_frame frame;
    if(!s->seen || (r->flags&LEMONADES_INPUT_RESYNC) || r->sequence-s->sequence!=1 || r->dropped!=s->dropped){
        if(lemonades_hid_release_all(&s->touch,r->time,&next,&frame)){s->poisoned=1;return -2;}
        if(submit(s,&next,&frame,sink,context))return -2;
    }
    for(unsigned i=0;i<LEMONADES_INPUT_CONTACTS;i++){
        unsigned active=(r->active>>i)&1u;
        const struct lemonades_hid_contact *c=&s->touch.contacts[i];
        unsigned type=!c->active && active?1:c->active && !active?3:
            c->active && (c->x!=r->x[i] || c->y!=r->y[i])?2:0;
        if(!type)continue;
        if(lemonades_hid_prepare(&s->touch,r->time,type,i,r->x[i],r->y[i],&next,&frame)){
            s->poisoned=1;return -2;
        }
        if(submit(s,&next,&frame,sink,context))return -2;
    }
    s->touch.time=r->time;s->sequence=r->sequence;s->dropped=r->dropped;s->seen=1;return 0;
}
