#include "hid_touch.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
    struct lemonades_hid_state s={0},n,before;
    struct lemonades_hid_frame f,unchanged;
    assert(lemonades_hid_prepare(&s,10,1,0,0,65535,&n,&f)==0);
    assert(!s.contacts[0].active && n.contacts[0].active && f.count==1 && f.active);
    assert(f.fingers[0].index==1 && f.fingers[0].identity==1 && f.fingers[0].mask==3);
    assert(f.x==0 && f.y==65535 && f.mask==2);s=n;
    assert(lemonades_hid_prepare(&s,11,1,9,65535,0,&n,&f)==0);s=n;
    assert(f.count==2 && f.fingers[0].mask==0 && f.fingers[1].identity==2);
    assert(lemonades_hid_prepare(&s,12,2,0,30000,40000,&n,&f)==0);s=n;
    assert(f.mask==4 && f.fingers[0].mask==4 && f.fingers[1].mask==0);
    before=s;memset(&n,0xa5,sizeof(n));memset(&f,0x5a,sizeof(f));unchanged=f;
    struct lemonades_hid_state old_n=n;
    assert(lemonades_hid_prepare(&s,13,1,0,0,0,&n,&f)==LEMONADES_HID_SEQUENCE);
    assert(!memcmp(&n,&old_n,sizeof(n)) && !memcmp(&f,&unchanged,sizeof(f)));
    assert(lemonades_hid_prepare(&s,13,2,1,0,0,&n,&f)==LEMONADES_HID_SEQUENCE);
    assert(lemonades_hid_prepare(&s,9,2,0,0,0,&n,&f)==LEMONADES_HID_SEQUENCE);
    assert(lemonades_hid_prepare(&s,13,2,10,0,0,&n,&f)==LEMONADES_HID_INVALID);
    assert(lemonades_hid_prepare(&s,13,2,0,65536,0,&n,&f)==LEMONADES_HID_INVALID);
    assert(lemonades_hid_prepare(&s,13,4,0,0,0,&n,&f)==LEMONADES_HID_INVALID);
    assert(!memcmp(&s,&before,sizeof(s)) && !memcmp(&n,&old_n,sizeof(n)) && !memcmp(&f,&unchanged,sizeof(f)));
    assert(lemonades_hid_prepare(&s,13,3,0,30000,40000,&n,&f)==0);s=n;
    assert(f.active && f.count==2 && !f.fingers[0].active && f.fingers[1].active);
    assert(lemonades_hid_prepare(&s,14,1,0,1,2,&n,&f)==0);s=n;
    assert(f.fingers[0].identity==3); /* same slot, new contact lifetime */
    assert(lemonades_hid_release_all(&s,15,&n,&f)==0);
    assert(!f.active && f.count==2 && f.mask==2);
    assert(!f.fingers[0].active && !f.fingers[1].active);
    assert(s.contacts[0].active && s.contacts[9].active); /* failed sink: no commit */
    struct lemonades_hid_frame retry;
    assert(lemonades_hid_release_all(&s,15,&n,&retry)==0 && !memcmp(&f,&retry,sizeof(f)));
    s=n;assert(lemonades_hid_release_all(&s,16,&n,&f)==0 && f.count==0);
    for(unsigned i=0;i<10;i++){
        assert(lemonades_hid_prepare(&s,20+i,1,i,i,65535-i,&n,&f)==0);s=n;
        assert(f.count==i+1);
    }
    assert(lemonades_hid_release_all(&s,30,&n,&f)==0 && f.count==10 && !f.active);
    s=n;s.last_identity=UINT32_MAX;
    assert(lemonades_hid_prepare(&s,31,1,0,0,0,&n,&f)==LEMONADES_HID_ID_EXHAUSTED);
    memset(&s,0,sizeof(s));
    for(unsigned i=1;i<=100000;i++){
        unsigned finger=((i-1)/3)%10,type=i%3==1?1:i%3==2?2:3;
        /* Explicit lifetime triplets, covering all ten slots and coordinate bounds. */
        int r=lemonades_hid_prepare(&s,i,type,finger,(i*17)%65536,(i*31)%65536,&n,&f);
        assert(r==0 && f.count==1 && f.fingers[0].index==finger+1);s=n;
    }
    puts("HID TOUCH HOST PASS transactions multi-contact release invalid-input stress");
}
