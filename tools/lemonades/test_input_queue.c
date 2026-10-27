#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "lemonades_input_queue.h"
#include "hid_stream.h"
_Static_assert(sizeof(struct lemonades_input_record)==120,"wire ABI");
static struct lemonades_input_queue queue;
struct sink_state { unsigned count,fail_at,releases; uint32_t last_identity; };
static int sink(void *context,const struct lemonades_hid_frame *f)
{
    struct sink_state *s=context;
    s->count++;
    if(s->count==s->fail_at)return 0;
    if(!f->active)s->releases++;
    for(unsigned i=0;i<f->count;i++)if(f->fingers[i].identity>s->last_identity)s->last_identity=f->fingers[i].identity;
    return 1;
}
static void check_state(struct lemonades_hid_stream *s,struct lemonades_input_record *r)
{
    for(unsigned i=0;i<10;i++){
        assert(s->touch.contacts[i].active==((r->active>>i)&1));
        if(s->touch.contacts[i].active)assert(s->touch.contacts[i].x==r->x[i] && s->touch.contacts[i].y==r->y[i]);
    }
}
int main(void)
{
    struct lemonades_input_record r;
    struct lemonades_hid_stream stream={0};struct sink_state out={0};
    lemonades_input_resync(&queue,1,LEMONADES_INPUT_OPEN);
    assert(lemonades_input_pop(&queue,&r) && r.flags==LEMONADES_INPUT_OPEN && r.sequence==1);
    assert(lemonades_hid_consume(&stream,&r,sink,&out)==0 && out.count==0);
    assert(lemonades_input_post(&queue,2,1,0,100,200,1)==1);
    assert(lemonades_input_pop(&queue,&r) && (r.flags&LEMONADES_INPUT_SYNTHETIC));
    assert(lemonades_hid_consume(&stream,&r,sink,&out)==0 && out.count==1);
    uint32_t identity=stream.touch.contacts[0].identity;
    /* Lost UP then new DOWN in the same slot: final mask alone is insufficient. */
    assert(lemonades_input_post(&queue,3,3,0,100,200,0)==1);
    assert(lemonades_input_post(&queue,4,1,0,101,201,0)==1);
    for(unsigned i=0;i<100;i++)assert(lemonades_input_post(&queue,5+i,2,0,i,i,0)==1);
    assert(lemonades_input_pop(&queue,&r) && r.flags&LEMONADES_INPUT_OVERFLOW && r.dropped==64);
    assert(lemonades_hid_consume(&stream,&r,sink,&out)==0);
    assert(out.releases==1 && stream.touch.contacts[0].identity>identity);check_state(&stream,&r);
    while(lemonades_input_pop(&queue,&r)){assert(!lemonades_hid_consume(&stream,&r,sink,&out));check_state(&stream,&r);}
    struct lemonades_input_queue before=queue;
    assert(!lemonades_input_post(&queue,105,1,0,2,3,0));
    assert(!lemonades_input_post(&queue,105,2,10,2,3,0));
    assert(!memcmp(&before,&queue,sizeof(queue)));
    /* Fault/open markers restore all ten contacts and cannot leave stale ones. */
    for(unsigned i=1;i<10;i++)assert(lemonades_input_post(&queue,106+i,1,i,i,i,0));
    lemonades_input_resync(&queue,120,LEMONADES_INPUT_READ_FAULT);
    assert(lemonades_input_pop(&queue,&r));
    assert(!lemonades_hid_consume(&stream,&r,sink,&out));check_state(&stream,&r);
    assert(r.active==1023 && r.flags&LEMONADES_INPUT_SYNTHETIC);
    /* A sequence gap alone also forces all-up before recreating contacts. */
    r.sequence+=3;r.time++;
    unsigned releases=out.releases;
    assert(!lemonades_hid_consume(&stream,&r,sink,&out) && out.releases==releases+1);
    struct lemonades_hid_stream saved=stream;
    assert(lemonades_hid_consume(&stream,&r,sink,&out)==-1 && !memcmp(&saved,&stream,sizeof(saved)));
    r.sequence++;r.version=99;
    assert(lemonades_hid_consume(&stream,&r,sink,&out)==-1 && !memcmp(&saved,&stream,sizeof(saved)));
    r.version=1;r.flags=LEMONADES_INPUT_OVERFLOW;r.time++;
    out.fail_at=out.count+2; /* Release accepted; first restored DOWN fails. */
    assert(lemonades_hid_consume(&stream,&r,sink,&out)==-2 && stream.poisoned);
    unsigned sent=out.count;
    assert(lemonades_hid_consume(&stream,&r,sink,&out)==-2 && out.count==sent);
    /* New service starts from a complete snapshot, independent of old lifetimes. */
    memset(&stream,0,sizeof(stream));out.fail_at=0;
    assert(!lemonades_hid_consume(&stream,&r,sink,&out));check_state(&stream,&r);
    /* 100k updates, deliberate reader stalls/overflow, compare to full state. */
    for(unsigned i=0;i<100000;i++){
        assert(lemonades_input_post(&queue,1000+i,2,i%10,i%65536,(i*7)%65536,0));
        if(i%97==0)while(lemonades_input_pop(&queue,&r)){
            if(r.sequence<=stream.sequence)continue;
            assert(!lemonades_hid_consume(&stream,&r,sink,&out));check_state(&stream,&r);
        }
    }
    queue.current.sequence=UINT64_MAX;lemonades_input_resync(&queue,200000,LEMONADES_INPUT_OPEN);
    assert(queue.exhausted && lemonades_input_post(&queue,200001,2,0,0,0,0)==-1);
    puts("INPUT QUEUE HOST PASS");return 0;
}
