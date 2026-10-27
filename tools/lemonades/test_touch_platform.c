/* Compile the real platform, XNU bridge and GENI/session code. Only the OS
 * mapping/time/DT/input services are replaced. Register RAM is driven manually;
 * this does not model the electrical bus or prove physical compatibility. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <arm/machine_routines.h>
#include <pexpert/device_tree.h>
#include <sys/lemonades_touch.h>
#include <sys/lemonades_touch_platform.h>
#include "s3908_geni.h"

int startup_phase = 1;
static const char *board = "lemonades";
static const uintptr_t physical[] = {0x118000, 0x150000, 0xf524000, 0xa94000};
static uint32_t initial[4][0x4000 / 4];
static uint32_t *live[4];
static unsigned maps, unmaps, fail_map, bound, posted;
static uint64_t milliseconds;

uint64_t mach_absolute_time(void) { return milliseconds * 1000000; }
void absolutetime_to_nanoseconds(uint64_t time, uint64_t *ns) { *ns = time; }
int SecureDTLookupEntry(DTEntry parent, const char *path, DTEntry *entry)
{ (void)parent; assert(!strcmp(path,"/chosen")); *entry=(DTEntry)1; return 0; }
int SecureDTGetProperty(DTEntry entry, const char *name, const void **value, unsigned *size)
{ (void)entry; assert(!strcmp(name,"hackios,board")); *value=board; *size=(unsigned)strlen(board)+1; return 0; }
void redwood_touch_post(uint32_t type, uint32_t id, uint32_t x, uint32_t y)
{ (void)type; (void)id; (void)x; (void)y; ++posted; }

vm_offset_t ml_io_map_unmappable(vm_offset_t pa, vm_size_t size, uint32_t flags)
{
    unsigned i = maps++;
    assert(i < 4 && pa == physical[i] && size == 0x4000 && flags == 7);
    assert(!live[i]);
    if (fail_map == i+1) return 0;
    live[i] = malloc(size);
    assert(live[i]);
    memcpy(live[i], initial[i], size);
    ++bound;
    return (uintptr_t)live[i];
}
void ml_io_unmap(vm_offset_t address, vm_size_t size)
{
    assert(bound && size == 0x4000);
    unsigned i = --bound;
    assert(address == (uintptr_t)live[i]); /* strict reverse order */
    free(live[i]); live[i]=NULL; ++unmaps;
}
static void prepare(void)
{
    assert(!bound && lemonades_touch_platform_state()==LTP_CLOSED);
    memset(initial,0,sizeof(initial));
    initial[1][0x2008/4]=(1u<<27)|(1u<<20)|(1u<<21);
    initial[2][0]=initial[2][0x1000/4]=1u<<2;
    initial[2][0x2000/4]=1u<<9;
    initial[2][0x2004/4]=2;
    initial[2][0x3004/4]=1;
    uint32_t *se=initial[3];
    se[SG_FW/4]=3u<<8;
    se[SG_HW_TX/4]=se[SG_HW_RX/4]=(32u<<24)|(4u<<16);
    se[SG_TX_PACK0/4]=se[SG_RX_PACK0/4]=0x7f8fe;
    se[SG_TX_PACK1/4]=se[SG_RX_PACK1/4]=0xffefe;
    se[SG_RX_WM/4]=1;
    se[SG_IRQ_EN/4]=SG_DONE|SG_TX_WATERMARK|SG_RX_WATERMARK|SG_RX_LAST|SG_ERRORS;
    maps=unmaps=fail_map=0; milliseconds=0;
}
static void rejected(int result, unsigned expected_maps)
{
    assert(lemonades_touch_platform_open(LTP_REQUIRED)==result);
    assert(maps==expected_maps && !bound);
    assert(lemonades_touch_platform_state()==LTP_CLOSED);
}
static void check_guards(void)
{
    prepare(); board="redwood"; rejected(LTP_ARGUMENT,0); board="lemonades";
    startup_phase=0; rejected(LTP_ARGUMENT,0); startup_phase=1;
    for (unsigned i=0;i<6;++i)
        assert(lemonades_touch_platform_open(LTP_REQUIRED ^ (1u<<i))==LTP_ARGUMENT);
    assert(lemonades_touch_platform_open(LTP_REQUIRED|64)==LTP_ARGUMENT && !maps);
    for (unsigned i=1;i<=4;++i) {
        prepare(); fail_map=i; rejected(LTP_MAPPING,i); assert(unmaps==i-1);
    }
    const unsigned bits[]={27,20,21};
    for (unsigned i=0;i<3;++i) {
        prepare(); initial[1][0x2008/4]^=1u<<bits[i]; rejected(LTP_CLOCK,2);
    }
    const unsigned clocks[]={4,8,0x5fc};
    for (unsigned i=0;i<3;++i) {
        prepare(); initial[0][clocks[i]/4]=1u<<31; rejected(LTP_CLOCK,2);
    }
    const unsigned offsets[]={0,0x1000,0x2000,0x2004,0x3000,0x3000};
    const unsigned values[]={0,0,0,0,4,1u<<9};
    for (unsigned i=0;i<6;++i) {
        prepare(); initial[2][offsets[i]/4]=values[i]; rejected(LTP_PIN,3);
    }
    prepare(); initial[3][SG_FW/4]=0; rejected(S3908_GENI_UNPREPARED,4);
}
static void check_lifecycle(void)
{
    prepare();
    assert(lemonades_touch_platform_open(LTP_REQUIRED)==0 && maps==4);
    assert(lemonades_touch_platform_open(LTP_REQUIRED)==LTP_BUSY && maps==4);
    assert(!memcmp(live[3],initial[3],0x4000)); /* open never writes SE */
    assert(lemonades_touch_platform_close()==S3908_GENI_CANCELLED);
    assert(!bound && unmaps==4 && lemonades_touch_platform_state()==LTP_CLOSED);
    assert(lemonades_touch_bus_poll(0,0)<0); /* detached callbacks */
    assert(lemonades_touch_platform_close()==0);
    for (unsigned abort=0;abort<2;++abort) {
        prepare(); assert(lemonades_touch_platform_open(LTP_REQUIRED)==0);
        assert(lemonades_touch_platform_service()==1);
        assert(live[3][SG_CMD/4]!=0);
        live[3][SG_STATUS/4]=1;
        assert(lemonades_touch_platform_close()==1 && bound==4);
        assert(lemonades_touch_platform_state()==LTP_STOPPING);
        if (abort) { milliseconds=50; assert(lemonades_touch_platform_service()==1 && bound==4); }
        live[3][SG_STATUS/4]=0;
        live[3][SG_IRQ/4]=abort ? SG_ABORT : SG_CANCEL;
        milliseconds++;
        assert(lemonades_touch_platform_service()==S3908_GENI_CANCELLED);
        assert(!bound && unmaps==4 && lemonades_touch_platform_state()==LTP_CLOSED);
        assert(lemonades_touch_bus_poll(milliseconds,0)<0);
    }
    /* Finish the initial TX, then prove GPIO39 is sampled as active low. */
    prepare(); assert(lemonades_touch_platform_open(LTP_REQUIRED)==0);
    assert(lemonades_touch_platform_service()==1);
    live[3][SG_STATUS/4]=1;
    live[3][SG_IRQ/4]=SG_TX_WATERMARK;
    milliseconds++; assert(lemonades_touch_platform_service()==1);
    live[3][SG_STATUS/4]=0;
    live[3][SG_IRQ/4]=SG_DONE;
    milliseconds++; assert(lemonades_touch_platform_service()==1);
    live[3][SG_IRQ/4]=0;
    uint32_t command=live[3][SG_CMD/4];
    milliseconds++; assert(lemonades_touch_platform_service()==0);
    assert(live[3][SG_CMD/4]==command);
    live[2][0x3004/4]=0;
    milliseconds++; assert(lemonades_touch_platform_service()==1);
    assert((live[3][SG_CMD/4]>>27)==2); /* RX */
    /* A spontaneous NACK also reaches cleanup without an explicit close. */
    live[3][SG_STATUS/4]=1;
    live[3][SG_IRQ/4]=SG_NACK;
    milliseconds++; assert(lemonades_touch_platform_service()==1 && bound==4);
    live[3][SG_STATUS/4]=0;
    live[3][SG_IRQ/4]=SG_CANCEL;
    milliseconds++; assert(lemonades_touch_platform_service()==S3908_GENI_NACK);
    assert(!bound && lemonades_touch_platform_state()==LTP_CLOSED);
    /* Terminal cancellation without ACK must retain every mapping and lease. */
    prepare(); assert(lemonades_touch_platform_open(LTP_REQUIRED)==0);
    assert(lemonades_touch_platform_service()==1);
    live[3][SG_STATUS/4]=1;
    assert(lemonades_touch_platform_close()==1);
    milliseconds=50; assert(lemonades_touch_platform_service()==1);
    milliseconds=100; assert(lemonades_touch_platform_service()==LTP_STUCK);
    assert(bound==4 && !unmaps && lemonades_touch_platform_state()==LTP_QUARANTINED);
    assert(lemonades_touch_bus_unbind()<0);
    assert(lemonades_touch_platform_close()==LTP_STUCK);
    assert(lemonades_touch_platform_service()==LTP_STUCK);
    assert(lemonades_touch_platform_open(LTP_REQUIRED)==LTP_BUSY && maps==4);
    assert(!posted);
}
int main(void)
{
    check_guards(); check_lifecycle();
    puts("Touch platform: board/VM/lease guards, four map failures, clock/pin/FIFO rejection, idle/cancel/abort detach and stuck quarantine: PASS");
}
