/* Reuse the standalone BSD probe and its console/syscall helpers unchanged.
 * Mach traps return a kern_return_t/port directly, NOT BSD carry + errno.
 * Tests local task port rights and request/reply queues, not cross-task bootstrap
 * or launchd. Uses packed mach_msg2, as required for platform binaries by pinned XNU. */
#define start bsd_probe_start
#include "abi_probe.c"
#undef start
#include <mach/message.h>
#include <mach/port.h>
#include <mach/kern_return.h>
#include <mach/task.h>
#include <stddef.h>

enum { MT_allocate=16, MT_deallocate=18, MT_mod_refs=19,
    MT_insert_right=21, MT_task_self=28, MT_msg2=47 };
/* mach_msg2 private option from the pinned XNU message.h, absent in this SDK. */
#define PROBE_MACH64_SEND_MQ_CALL 0x0000000400000000ull
#define PROBE_MACH64_SEND_KOBJECT_CALL 0x0000000200000000ull
_Static_assert(sizeof(mach_msg_header_t)==24,"ARM64 user Mach header ABI");
_Static_assert(sizeof(mach_port_name_t)==4,"Mach port ABI");

static long trap(unsigned number, u64 a, u64 b, u64 c, u64 d, u64 e, u64 f, u64 g, u64 h)
{
    register long x16 __asm__("x16")=-(long)number;
    register u64 x0 __asm__("x0")=a, x1 __asm__("x1")=b;
    register u64 x2 __asm__("x2")=c, x3 __asm__("x3")=d;
    register u64 x4 __asm__("x4")=e, x5 __asm__("x5")=f;
    register u64 x6 __asm__("x6")=g, x7 __asm__("x7")=h;
    __asm__ volatile("svc #0x80" : "+r"(x0) : "r"(x16),"r"(x1),"r"(x2),
        "r"(x3),"r"(x4),"r"(x5),"r"(x6),"r"(x7) : "memory","cc");
    return (long)x0;
}
static void must(long status, const char *stage)
{
    if (status!=KERN_SUCCESS) fail(stage);
}
static mach_port_name_t allocate(mach_port_name_t task)
{
    mach_port_name_t name=MACH_PORT_NULL;
    must(trap(MT_allocate,task,MACH_PORT_RIGHT_RECEIVE,(u64)&name,0,0,0,0,0),"Mach allocate");
    if (!MACH_PORT_VALID(name)) fail("Mach allocated name");
    return name;
}
struct packet {
    mach_msg_header_t header;
    unsigned sequence, value;
    unsigned char trailer[256];
};
static struct packet packet;
enum { SEND_BYTES=offsetof(struct packet,trailer) };
_Static_assert(SEND_BYTES==32,"inline message ABI");
static void clear_packet(void)
{
    volatile unsigned char *bytes=(void *)&packet;
    for (unsigned i=0;i<sizeof(packet);++i) bytes[i]=0;
}
static unsigned message(int send, mach_port_name_t receive)
{
    u64 options = send ? (MACH_SEND_MSG|MACH_SEND_TIMEOUT) : (MACH_RCV_MSG|MACH_RCV_TIMEOUT);
    const mach_msg_header_t *h=&packet.header;
    return (unsigned)trap(MT_msg2,(u64)&packet,options|PROBE_MACH64_SEND_MQ_CALL,
        (u64)h->msgh_bits|((u64)(send?SEND_BYTES:0)<<32),
        (u64)h->msgh_remote_port|((u64)h->msgh_local_port<<32),
        (u64)h->msgh_voucher_port|((u64)(unsigned)h->msgh_id<<32),
        (u64)receive<<32,send?0:sizeof(packet),0);
}
static void exercise(mach_port_name_t task)
{
    mach_port_name_t server=allocate(task), reply=allocate(task);
    must(trap(MT_insert_right,task,server,server,MACH_MSG_TYPE_MAKE_SEND,0,0,0,0),"Mach send right");
    clear_packet();
    if (message(0,server)!=MACH_RCV_TIMED_OUT) fail("Mach empty queue timeout");
    packet.header.msgh_bits=MACH_MSGH_BITS(MACH_MSG_TYPE_COPY_SEND,MACH_MSG_TYPE_MAKE_SEND_ONCE);
    packet.header.msgh_size=SEND_BYTES;
    packet.header.msgh_remote_port=server;
    packet.header.msgh_local_port=reply;
    packet.header.msgh_id=0x3908;
    packet.sequence=71; packet.value=0xabcdef42;
    must(message(1,MACH_PORT_NULL),"Mach request send");
    clear_packet();
    must(message(0,server),"Mach request receive");
    if (packet.header.msgh_size!=SEND_BYTES || packet.header.msgh_id!=0x3908 ||
        packet.header.msgh_local_port!=server || !MACH_PORT_VALID(packet.header.msgh_remote_port) ||
        MACH_MSGH_BITS_REMOTE(packet.header.msgh_bits)!=MACH_MSG_TYPE_PORT_SEND_ONCE ||
        packet.sequence!=71 || packet.value!=0xabcdef42) fail("Mach request payload/rights");
    mach_port_name_t once=packet.header.msgh_remote_port;
    clear_packet();
    packet.header.msgh_bits=MACH_MSGH_BITS(MACH_MSG_TYPE_MOVE_SEND_ONCE,0);
    packet.header.msgh_size=SEND_BYTES;
    packet.header.msgh_remote_port=once;
    packet.header.msgh_id=0x3909;
    packet.sequence=72; packet.value=0x12345678;
    must(message(1,MACH_PORT_NULL),"Mach reply send");
    clear_packet();
    must(message(0,reply),"Mach reply receive");
    if (packet.header.msgh_id!=0x3909 || packet.header.msgh_size!=SEND_BYTES ||
        packet.header.msgh_local_port!=reply || packet.header.msgh_remote_port!=MACH_PORT_NULL ||
        packet.sequence!=72 || packet.value!=0x12345678) fail("Mach reply payload/rights");
    clear_packet();
    if (message(0,reply)!=MACH_RCV_TIMED_OUT) fail("Mach reply queue drained");
    /* Drop the send right first, then each receive right. All are self-owned. */
    must(trap(MT_deallocate,task,server,0,0,0,0,0,0),"Mach release send right");
    must(trap(MT_mod_refs,task,server,MACH_PORT_RIGHT_RECEIVE,(u64)-1,0,0,0,0),"Mach destroy server");
    must(trap(MT_mod_refs,task,reply,MACH_PORT_RIGHT_RECEIVE,(u64)-1,0,0,0,0),"Mach destroy reply");
}
/* A real MIG request to a kernel task port, using generated public SDK wire
 * types. Distinguish kobject from user queues in mach_msg2 CFI options. */
static union {
    __Request__task_info_t request;
    __Reply__task_info_t reply;
    unsigned char storage[1024];
} task_packet;
static void task_info_rpc(mach_port_name_t task)
{
    mach_port_name_t reply=allocate(task);
    volatile unsigned char *bytes=task_packet.storage;
    for (unsigned i=0;i<sizeof(task_packet);++i) bytes[i]=0;
    __Request__task_info_t *request=&task_packet.request;
    request->Head.msgh_bits=MACH_MSGH_BITS(MACH_MSG_TYPE_COPY_SEND,MACH_MSG_TYPE_MAKE_SEND_ONCE);
    request->Head.msgh_size=sizeof(*request);
    request->Head.msgh_remote_port=task;
    request->Head.msgh_local_port=reply;
    request->Head.msgh_id=3405;
    request->NDR.int_rep=NDR_INT_LITTLE_ENDIAN;
    request->flavor=MACH_TASK_BASIC_INFO;
    request->task_info_outCnt=MACH_TASK_BASIC_INFO_COUNT;
    must(trap(MT_msg2,(u64)&task_packet,
        MACH_SEND_MSG|MACH_RCV_MSG|MACH_SEND_TIMEOUT|MACH_RCV_TIMEOUT|PROBE_MACH64_SEND_KOBJECT_CALL,
        (u64)request->Head.msgh_bits|((u64)sizeof(*request)<<32),
        (u64)task|((u64)reply<<32),(u64)3405<<32,(u64)reply<<32,sizeof(task_packet),1000),"Mach task_info request");
    __Reply__task_info_t *response=&task_packet.reply;
    if (response->Head.msgh_id!=3505 || response->Head.msgh_local_port!=reply ||
        response->Head.msgh_remote_port!=MACH_PORT_NULL ||
        response->Head.msgh_bits&MACH_MSGH_BITS_COMPLEX ||
        response->Head.msgh_size!=offsetof(__Reply__task_info_t,task_info_out)+MACH_TASK_BASIC_INFO_COUNT*4 ||
        response->RetCode!=KERN_SUCCESS || response->task_info_outCnt!=MACH_TASK_BASIC_INFO_COUNT ||
        response->NDR.int_rep!=NDR_INT_LITTLE_ENDIAN) fail("Mach task_info reply");
    mach_task_basic_info_t info=(void *)response->task_info_out;
    if (!info->virtual_size || !info->resident_size) fail("Mach task_info memory accounting");
    must(trap(MT_mod_refs,task,reply,MACH_PORT_RIGHT_RECEIVE,(u64)-1,0,0,0,0),"Mach destroy MIG reply");
}
void start(void)
{
    struct result opened=CALL(SYS_open,"/dev/console",O_RDWR,0);
    if (opened.error) terminate(1);
    console=(int)opened.value;
    put("MACH BEGIN v1\n");
    mach_port_name_t task=(mach_port_name_t)trap(MT_task_self,0,0,0,0,0,0,0,0);
    if (!MACH_PORT_VALID(task)) fail("Mach task self");
    exercise(task); put("MACH PASS msg2-rpc\n");
    for (unsigned i=0;i<64;++i) exercise(task);
    put("MACH PASS rights-lifecycle\n");
    task_info_rpc(task); put("MACH PASS task-info-rpc\n");
    /* Keep the task-self control right for process lifetime, like libSystem.
     * XNU pins it; dropping its last uref returns KERN_INVALID_CAPABILITY. */
    put("MACH COMPLETE v1\n");
    close_fd(console);
    bsd_probe_start();
}
