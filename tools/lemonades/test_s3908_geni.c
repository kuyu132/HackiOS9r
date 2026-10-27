#include "s3908_transport.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/lemonades_touch.h>
#include <pexpert/device_tree.h>

struct model {
    uint32_t reg[1024], tx[64], rx[64];
    size_t tx_count, rx_count, length, moved;
    uint8_t input[32], output[32];
    int operation, reads, writes, barriers, cancel_ack, abort_ack, emulate;
    uint8_t message[517], command[131];
    size_t message_size, message_offset, command_size;
    unsigned commands, transactions;
};
static struct s3908_event events[10];
static size_t event_count;
static const char *board = "lemonades";
static struct s3908_event posted[100];
static size_t posted_count;
int SecureDTLookupEntry(DTEntry from, const char *path, DTEntry *entry)
{ (void)from; assert(!strcmp(path,"/chosen")); *entry=(DTEntry)1; return kSuccess; }
int SecureDTGetProperty(DTEntry entry, const char *key, const void **value, unsigned *size)
{ (void)entry; assert(!strcmp(key,"hackios,board")); *value=board; *size=(unsigned)strlen(board)+1; return kSuccess; }
void redwood_touch_post(uint32_t type, uint32_t finger, uint32_t x, uint32_t y)
{ assert(posted_count<100); posted[posted_count++]=(struct s3908_event){type,finger,x,y}; }


static void response(struct model *m, uint8_t code, const uint8_t *p, size_t n)
{
    assert(!m->message_size && n + 5 <= sizeof(m->message));
    m->message[0]=0xa5; m->message[1]=code;
    m->message[2]=(uint8_t)n; m->message[3]=(uint8_t)(n >> 8);
    if (n) memcpy(m->message + 4, p, n);
    m->message[n + 4]=0x5a; m->message_size=n+5; m->message_offset=0;
}
static void controller_write(struct model *m)
{
    size_t prefix=m->command_size ? 1 : 0;
    if (prefix) assert(m->output[0]==1);
    assert(m->command_size + m->length - prefix <= sizeof(m->command));
    memcpy(m->command + m->command_size, m->output + prefix, m->length - prefix);
    m->command_size += m->length - prefix;
    if (m->command_size < 3 || m->command_size < (size_t)m->command[1]+3) return;
    assert(m->command_size == (size_t)m->command[1]+3 && m->command[2]==0);
    const uint8_t order[]={2,0x20,6,0x26,0x25,5};
    assert(m->commands < 6 && m->command[0]==order[m->commands++]);
    uint8_t payload[128]={0}; size_t n=0;
    switch (m->command[0]) {
    case 2: n=24; payload[0]=1; payload[1]=1; payload[22]=17; break;
    case 0x20:
        n=48; payload[12]=128; payload[14]=121;
        payload[32]=0x37; payload[33]=4; payload[34]=0x5f; payload[35]=9; payload[36]=10;
        break;
    case 6: case 5: assert(m->command[1]==1 && m->command[3]==0x11); break;
    case 0x26:
        assert(m->command[1]==128 && !memcmp(m->command+3,s3908_normal_config,19));
        for (size_t i=22;i<131;i++) assert(m->command[i]==0);
        break;
    case 0x25: n=128; memcpy(payload,s3908_normal_config,19); break;
    }
    response(m,1,payload,n); m->command_size=0;
}
static void controller_read(struct model *m)
{
    assert(m->message_size);
    size_t prefix=m->message_offset ? 2 : 0;
    if (prefix) { m->input[0]=0xa5; m->input[1]=3; }
    for (size_t i=prefix;i<m->length;i++)
        m->input[i]=m->message_offset < m->message_size ? m->message[m->message_offset++] : 0xee;
    /* Same documented single-padding-byte omission as continued-read helper. */
    if (m->message_size-m->message_offset <= 1) m->message_size=m->message_offset=0;
}
static uint32_t read_reg(void *ctx, uint32_t reg)
{
    struct model *m=ctx; assert(reg%4==0 && reg<sizeof(m->reg)); ++m->reads;
    if (reg==SG_TX_STATUS) return (uint32_t)m->tx_count;
    if (reg==SG_RX_STATUS) return (uint32_t)m->rx_count;
    if (reg==SG_RX_FIFO) {
        assert(m->rx_count); uint32_t value=m->rx[0];
        memmove(m->rx,m->rx+1,--m->rx_count*sizeof(*m->rx)); return value;
    }
    return m->reg[reg/4];
}
static void write_reg(void *ctx, uint32_t reg, uint32_t value)
{
    struct model *m=ctx; assert(reg%4==0 && reg<sizeof(m->reg)); ++m->writes;
    if (reg==SG_CLEAR) { m->reg[SG_IRQ/4]&=~value; return; }
    if (reg==SG_TX_FIFO) {
        assert(m->tx_count < ((m->reg[SG_HW_TX/4]>>16)&63)); m->tx[m->tx_count++]=value; return;
    }
    if (reg==SG_CMD) {
        assert(!m->operation && !m->tx_count && !m->rx_count);
        assert((value & ((1u<<27)-1))==(0x4bu<<9));
        m->operation=(int)(value>>27); assert(m->operation==1 || m->operation==2);
        m->length=m->reg[(m->operation==1 ? SG_TX_LEN:SG_RX_LEN)/4];
        assert(m->length && m->length<=32); m->moved=0; ++m->transactions;
        m->reg[SG_STATUS/4]=1;
        if (m->emulate && m->operation==2) controller_read(m);
    }
    if (reg==SG_CTRL) {
        assert(value==4 || value==2);
        if ((value==4 && m->cancel_ack) || (value==2 && m->abort_ack)) {
            m->reg[SG_IRQ/4]|=value==4 ? SG_CANCEL : SG_ABORT;
            m->reg[SG_STATUS/4]=0; m->operation=0;
        }
    }
    m->reg[reg/4]=value;
}
static void barrier(void *ctx) { ++((struct model *)ctx)->barriers; }
static void initialize(struct model *m, unsigned depth)
{
    memset(m,0,sizeof(*m));
    m->reg[SG_FW/4]=3u<<8;
    m->reg[SG_HW_TX/4]=m->reg[SG_HW_RX/4]=(32u<<24)|(depth<<16);
    m->reg[SG_TX_PACK0/4]=m->reg[SG_RX_PACK0/4]=0x7f8fe;
    m->reg[SG_TX_PACK1/4]=m->reg[SG_RX_PACK1/4]=0xffefe;
    m->reg[SG_IRQ_EN/4]=SG_DONE|SG_TX_WATERMARK|SG_RX_WATERMARK|SG_RX_LAST|SG_ERRORS;
    m->reg[SG_RX_WM/4]=depth-1; m->cancel_ack=m->abort_ack=1;
}
static void tick(struct model *m)
{
    if (m->operation==1) {
        for (size_t w=0;w<m->tx_count;w++)
            for (unsigned b=0;b<4 && m->moved<m->length;b++)
                m->output[m->moved++]=(uint8_t)(m->tx[w]>>(b*8));
        m->tx_count=0;
        if (m->moved==m->length) {
            m->reg[SG_IRQ/4]|=SG_DONE; m->reg[SG_STATUS/4]=0; m->operation=0;
            if (m->emulate) controller_write(m);
        } else if (m->reg[SG_TX_WM/4]) m->reg[SG_IRQ/4]|=SG_TX_WATERMARK;
    } else if (m->operation==2 && !m->rx_count) {
        unsigned depth=(m->reg[SG_HW_RX/4]>>16)&63;
        while (m->rx_count<depth && m->moved<m->length) {
            uint32_t value=0;
            for (unsigned b=0;b<4 && m->moved<m->length;b++) value|=(uint32_t)m->input[m->moved++]<<(b*8);
            m->rx[m->rx_count++]=value;
        }
        if (m->moved==m->length) {
            m->reg[SG_IRQ/4]|=SG_RX_LAST|SG_DONE; m->reg[SG_STATUS/4]=0; m->operation=0;
        } else m->reg[SG_IRQ/4]|=SG_RX_WATERMARK;
    }
}
static void bind(struct model *m, struct s3908_geni *bus)
{
    *bus=(struct s3908_geni){0};
    struct s3908_geni_io io={m,read_reg,write_reg,barrier};
    int writes=m->writes;
    assert(s3908_geni_bind(bus,&io)==0 && m->writes==writes);
}
static void check_transfer_sizes(void)
{
    for (unsigned depth=2;depth<=8;depth++) for (size_t n=1;n<=32;n++) for (int reading=0;reading<=1;reading++) {
        struct model m; struct s3908_geni bus;
        initialize(&m,depth); bind(&m,&bus);
        uint8_t bytes[32]; for (size_t i=0;i<32;i++) bytes[i]=m.input[i]=(uint8_t)(n+i*37);
        assert(s3908_geni_start(&bus,reading,bytes,n,0)==1);
        int status=1;
        for (uint64_t now=1;now<40 && status==1;now++) { tick(&m); status=s3908_geni_poll(&bus,now); }
        assert(status==0 && bus.phase==SG_IDLE && bus.offset==n && m.barriers);
        assert(!memcmp(reading ? bus.data:m.output,bytes,n));
    }
}
static void check_faults(void)
{
    struct model m; struct s3908_geni bus;
    struct s3908_geni_io io={&m,read_reg,write_reg,barrier};
    const unsigned regs[]={SG_FW,SG_FIFO_DISABLE,SG_DMA,SG_GSI,SG_STATUS,SG_TX_PACK0,SG_RX_PACK1,SG_IRQ_EN,SG_RX_WM,SG_HW_TX};
    for (size_t i=0;i<sizeof(regs)/sizeof(regs[0]);i++) {
        initialize(&m,4); bus=(struct s3908_geni){0}; m.reg[regs[i]/4]^=1;
        if (regs[i]==SG_FW) m.reg[SG_FW/4]=1u<<8;
        if (regs[i]==SG_HW_TX) m.reg[SG_HW_TX/4]=32u<<24;
        if (regs[i]==SG_RX_WM) m.reg[SG_RX_WM/4]=4;
        assert(s3908_geni_bind(&bus,&io)==S3908_GENI_UNPREPARED && m.writes==0);
    }
    const uint32_t faults[]={SG_NACK,SG_ARB,1u<<3,1u<<24};
    for (size_t i=0;i<4;i++) {
        initialize(&m,4); bind(&m,&bus);
        uint8_t b=0;
        assert(s3908_geni_start(&bus,0,&b,1,0)==1);
        m.reg[SG_IRQ/4]=SG_DONE|faults[i];
        assert(s3908_geni_poll(&bus,1)==1 && bus.phase==SG_CANCELLING);
        assert(s3908_geni_poll(&bus,2)<0 && bus.phase==SG_FAILED && bus.recovery==1);
        assert(s3908_geni_start(&bus,0,&b,1,3)==S3908_GENI_UNPREPARED);
    }
    for (unsigned ack=0;ack<3;ack++) {
        initialize(&m,4); bind(&m,&bus); m.cancel_ack=ack==2; m.abort_ack=ack==1;
        uint8_t b=0; assert(s3908_geni_start(&bus,0,&b,1,0)==1);
        assert(s3908_geni_poll(&bus,600)==1);
        int result=s3908_geni_poll(&bus,650);
        if (ack!=2) { assert(result==1); result=s3908_geni_poll(&bus,700); }
        assert(result==S3908_GENI_TIMEOUT && bus.recovery==(ack==2 ? 1:ack==1 ? 2:-1));
    }
    initialize(&m,4); bind(&m,&bus); uint8_t b=0;
    assert(s3908_geni_start(&bus,0,&b,1,0)==1);
    m.reg[SG_IRQ/4]=SG_DONE|SG_TX_WATERMARK; m.reg[SG_STATUS/4]=0;
    assert(s3908_geni_poll(&bus,1)==1 && bus.error==S3908_GENI_IO && !bus.offset);
    initialize(&m,4); bind(&m,&bus);
    assert(s3908_geni_start(&bus,1,NULL,1,0)==1);
    m.rx_count=2; m.reg[SG_IRQ/4]=SG_RX_LAST|SG_DONE;
    assert(s3908_geni_poll(&bus,1)==1 && bus.error==S3908_GENI_IO && !bus.offset);
}
static void check_pipeline(void)
{
    for (unsigned depth=2;depth<=8;depth++) {
        struct model m; struct s3908_geni bus; struct s3908_session session={0};
        struct s3908_transport transport={0};
        initialize(&m,depth); bind(&m,&bus); m.emulate=1;
        assert(s3908_transport_start(&transport,&bus,&session,0,events,&event_count)==0);
        uint64_t now=0;
        for (;now<900 && session.phase!=S3908_READY;now++) {
            tick(&m);
            assert(s3908_transport_poll(&transport,now,m.message_size!=0,events,&event_count)>=0);
            assert(event_count==0);
        }
        assert(session.phase==S3908_READY && m.commands==6 && m.transactions>15);
        const uint8_t touch[]={0,0x13,0x37,4,0x5f,9,0,0,0,0,0,0,0};
        response(&m,0x11,touch,sizeof(touch));
        for (;now<1000 && !event_count;now++) {
            tick(&m);
            assert(s3908_transport_poll(&transport,now,m.message_size!=0,events,&event_count)>=0);
        }
        assert(event_count==1 && events[0].type==1 && events[0].finger==3 && events[0].x==65535);
        /* Failure on a subsequent packet releases a previously active contact. */
        response(&m,0x11,touch,sizeof(touch));
        assert(s3908_transport_poll(&transport,now++,1,events,&event_count)==1);
        m.reg[SG_IRQ/4]=SG_NACK;
        assert(s3908_transport_poll(&transport,now++,1,events,&event_count)==1);
        assert(event_count==1 && events[0].type==3);
        assert(s3908_transport_poll(&transport,now++,1,events,&event_count)==S3908_GENI_NACK);
        unsigned transactions=m.transactions;
        assert(s3908_transport_poll(&transport,now++,1,events,&event_count)==S3908_GENI_NACK);
        assert(event_count==0 && m.transactions==transactions && !transport.running);
    }
}
static void check_kernel_bridge(void)
{
    struct model m; initialize(&m,4); m.emulate=1;
    struct s3908_geni_io io={&m,read_reg,write_reg,barrier};
    board="redwood";
    assert(lemonades_touch_bus_bind(&io,0)<0 && m.reads==0 && m.writes==0);
    board="lemonades";
    assert(lemonades_touch_bus_bind(&io,0)==0 && m.writes==0);
    assert(lemonades_touch_start(0)==S3908_BAD_ARGUMENT);
    assert(lemonades_touch_bus_quiesced()==0);
    assert(lemonades_touch_bus_unbind()<0);
    uint64_t now=0;
    for (;now<900 && (m.commands<6 || m.message_size || m.operation);now++) {
        tick(&m); assert(lemonades_touch_bus_poll(now,m.message_size!=0)>=0);
    }
    assert(m.commands==6 && !posted_count);
    const uint8_t touch[]={0,0x13,0x37,4,0x5f,9,0,0,0,0,0,0,0};
    response(&m,0x11,touch,sizeof(touch));
    for (;now<1000 && !posted_count;now++) {
        tick(&m); assert(lemonades_touch_bus_poll(now,m.message_size!=0)>=0);
    }
    assert(posted_count==1 && posted[0].type==1 && posted[0].x==65535);
    /* Stop during a read: one release, cancel acknowledgement must be drained. */
    response(&m,0x11,touch,sizeof(touch));
    assert(lemonades_touch_bus_poll(now++,1)==1);
    assert(lemonades_touch_bus_stop(now++)==1);
    assert(posted_count==2 && posted[1].type==3);
    assert(lemonades_touch_bus_poll(now++,1)==S3908_GENI_CANCELLED);
    unsigned transactions=m.transactions;
    assert(lemonades_touch_bus_poll(now++,1)==S3908_GENI_CANCELLED && m.transactions==transactions);
    assert(posted_count==2 && lemonades_touch_bus_quiesced()==1);
    assert(lemonades_touch_bus_unbind()==0);
    assert(lemonades_touch_bus_poll(now,0)<0 && m.transactions==transactions);
    /* A terminal error with failed abort is not permission to unmap registers. */
    initialize(&m,4); m.emulate=1; m.cancel_ack=m.abort_ack=0;
    assert(lemonades_touch_bus_bind(&io,0)==0);
    assert(lemonades_touch_bus_poll(0,0)==1);
    assert(lemonades_touch_bus_stop(1)==1);
    assert(lemonades_touch_bus_poll(51,0)==1);
    assert(lemonades_touch_bus_poll(101,0)==S3908_GENI_CANCELLED);
    assert(lemonades_touch_bus_quiesced()==0);
    assert(lemonades_touch_bus_unbind()<0);
}
int main(void)
{
    check_transfer_sizes(); check_faults(); check_pipeline(); check_kernel_bridge();
    puts("GENI FIFO: 448 size/depth/direction cases, failed preflight without writes, error priority, cancel/abort/stuck recovery: PASS");
    puts("S3908 transport: 7 FIFO depths, six-command handshake, continued RX/TX, XNU queue and stop/fault releases: PASS");
}
