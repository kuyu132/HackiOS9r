/* Allocation-free queue core shared by the actual kernel adapter and host tests.
 * All calls require the adapter's lock. No user copies or blocking operations.
 * A full queue is replaced by one complete current snapshot; loss is explicit.
 */
#ifndef LEMONADES_INPUT_QUEUE_H
#define LEMONADES_INPUT_QUEUE_H
#include <sys/lemonades_input.h>
#define LEMONADES_INPUT_CAPACITY 64u
struct lemonades_input_queue {
    struct lemonades_input_record current, records[LEMONADES_INPUT_CAPACITY];
    uint32_t head, count;
    int opened, reading, exhausted;
};
static inline void lemonades_input_append(struct lemonades_input_queue *q,uint64_t time,uint32_t flags)
{
    if(q->exhausted)return;
    if(q->current.sequence==UINT64_MAX){q->exhausted=1;return;}
    q->current.sequence++;
    q->current.time=time;
    q->current.version=LEMONADES_INPUT_VERSION;
    q->current.flags=(q->current.flags&LEMONADES_INPUT_SYNTHETIC)|flags;
    q->records[(q->head+q->count)%LEMONADES_INPUT_CAPACITY]=q->current;
    q->count++;
}
static inline void lemonades_input_resync(struct lemonades_input_queue *q,uint64_t time,uint32_t reason)
{
    if(UINT64_MAX-q->current.dropped<q->count){q->exhausted=1;return;}
    q->current.dropped+=q->count;
    q->head=0;q->count=0;
    lemonades_input_append(q,time,reason);
}
/* 1 accepted, 0 invalid transition/input, -1 counter exhausted. */
static inline int lemonades_input_post(struct lemonades_input_queue *q,uint64_t time,
    uint32_t type,uint32_t finger,uint32_t x,uint32_t y,int synthetic)
{
    if(q->exhausted)return -1;
    if(time<q->current.time || type<1 || type>5 || x>65535 || y>65535)return 0;
    if(type<=3){
        if(finger>=LEMONADES_INPUT_CONTACTS)return 0;
        uint32_t bit=1u<<finger;
        if(type==1 ? (q->current.active&bit)!=0 : (q->current.active&bit)==0)return 0;
        if(type==3)q->current.active&=~bit;else q->current.active|=bit;
        q->current.x[finger]=x;q->current.y[finger]=y;
    }else{
        if(finger<1 || finger>4)return 0;
        uint32_t bit=1u<<(finger-1);
        if(type==4 ? (q->current.buttons&bit)!=0 : (q->current.buttons&bit)==0)return 0;
        if(type==4)q->current.buttons|=bit;else q->current.buttons&=~bit;
    }
    if(synthetic)q->current.flags|=LEMONADES_INPUT_SYNTHETIC;
    if(q->count==LEMONADES_INPUT_CAPACITY)lemonades_input_resync(q,time,LEMONADES_INPUT_OVERFLOW);
    else lemonades_input_append(q,time,0);
    return q->exhausted?-1:1;
}
static inline int lemonades_input_pop(struct lemonades_input_queue *q,struct lemonades_input_record *record)
{
    if(!q->count)return 0;
    *record=q->records[q->head];q->head=(q->head+1)%LEMONADES_INPUT_CAPACITY;q->count--;return 1;
}
#endif
