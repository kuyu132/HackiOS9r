/* Cross-process Mach sender identity. The deliberately false inline identity is
 * ordinary message data; only the kernel-generated trailer is authoritative. */
#include <mach/mach.h>
#include <mach/message.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
#include <grp.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
extern kern_return_t bootstrap_look_up(mach_port_t,const char *,mach_port_t *);
#define AUDIT_SERVICE "net.hackios9r.bootstrap-probe"
struct audit_message {mach_msg_header_t header;uint32_t sequence;audit_token_t claimed_identity;};
union audit_buffer {struct audit_message message;unsigned char bytes[sizeof(struct audit_message)+MAX_TRAILER_SIZE];};
_Static_assert(sizeof(struct audit_message)%4==0,"Mach body alignment");
static int audit_fail(const char *stage,int code) {
    printf("BOOTSTRAP FAIL: audit %s result=%d\n",stage,code);fflush(stdout);return 1;
}

static mach_msg_return_t send_msg2(struct audit_message *message)
{
    mach_msg_header_t *h=&message->header;
    register uint64_t x0 __asm__("x0")=(uintptr_t)message;
    register uint64_t x1 __asm__("x1")=MACH_SEND_MSG|MACH_SEND_TIMEOUT|0x0000000400000000ull;
    register uint64_t x2 __asm__("x2")=h->msgh_bits|((uint64_t)h->msgh_size<<32);
    register uint64_t x3 __asm__("x3")=h->msgh_remote_port|((uint64_t)h->msgh_local_port<<32);
    register uint64_t x4 __asm__("x4")=h->msgh_voucher_port|((uint64_t)(uint32_t)h->msgh_id<<32);
    register uint64_t x5 __asm__("x5")=0,x6 __asm__("x6")=0,x7 __asm__("x7")=1000;
    register int64_t x16 __asm__("x16")=-47;
    __asm__ volatile("svc #0x80" : "+r"(x0) : "r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5),"r"(x6),"r"(x7),"r"(x16) : "memory","cc");
    return (mach_msg_return_t)x0;
}

int audit_probe_child(const char *role)
{
    uid_t uid;
    if(!strcmp(role,"root"))uid=0;
    else if(!strcmp(role,"mobile"))uid=501;
    else return audit_fail("unknown role",EINVAL);
    if(uid){gid_t group=uid;if(setgroups(1,&group) || setgid(uid) || setuid(uid))return audit_fail("drop credentials",errno);}
    if(getuid()!=uid || geteuid()!=uid || getgid()!=uid || getegid()!=uid)return audit_fail("child credentials",EINVAL);
    mach_port_t port=MACH_PORT_NULL;
    kern_return_t kr=bootstrap_look_up(bootstrap_port,AUDIT_SERVICE,&port);
    if(kr)return audit_fail("child lookup",kr);
    for(unsigned sequence=0;sequence<2;++sequence){
        struct audit_message message={0};
        message.header.msgh_bits=MACH_MSGH_BITS(MACH_MSG_TYPE_COPY_SEND,0);
        message.header.msgh_size=sizeof(message);message.header.msgh_remote_port=port;
        message.header.msgh_id=0x39a0;message.sequence=sequence;
        /* Claim the root parent, including for the sender that dropped to 501. */
        message.claimed_identity.val[5]=(uint32_t)getppid();
        kr=sequence?send_msg2(&message):mach_msg(&message.header,MACH_SEND_MSG|MACH_SEND_TIMEOUT,
            sizeof(message),0,MACH_PORT_NULL,1000,MACH_PORT_NULL);
        if(kr){mach_port_deallocate(mach_task_self(),port);return audit_fail("send",kr);}
    }
    mach_port_deallocate(mach_task_self(),port);return 0;
}

static int valid_audit_message(const union audit_buffer *buffer,pid_t child,uid_t uid,unsigned sequence,mach_port_t port)
{
    const struct audit_message *message=&buffer->message;
    if(message->header.msgh_size!=sizeof(*message) || message->header.msgh_id!=0x39a0 ||
       message->header.msgh_local_port!=port || message->header.msgh_remote_port!=MACH_PORT_NULL ||
       (message->header.msgh_bits&MACH_MSGH_BITS_COMPLEX) || message->sequence!=sequence)return 0;
    mach_msg_audit_trailer_t trailer;
    memcpy(&trailer,buffer->bytes+sizeof(*message),sizeof(trailer));
    if(trailer.msgh_trailer_type!=MACH_MSG_TRAILER_FORMAT_0 || trailer.msgh_trailer_size!=sizeof(trailer))return 0;
    const uint32_t *v=trailer.msgh_audit.val;
    /* Fixed XNU proc_calc_audit_token layout; audit UID/session are distinct
     * from POSIX UID and are intentionally not asserted as equal here. */
    if(v[1]!=uid || v[2]!=uid || v[3]!=uid || v[4]!=uid || v[5]!=(uint32_t)child || !v[7])return 0;
    if(v[5]==message->claimed_identity.val[5])return 0;
    return 1;
}

int check_audit_trailers(mach_port_t receiver)
{
    for(unsigned role=0;role<2;++role){
        char *args[]={"/bin/bootstrap_probe","audit-child",role?"mobile":"root",NULL};
        char *env[]={"PATH=/bin:/usr/bin",NULL};pid_t child=-1;
        int error=posix_spawn(&child,args[0],NULL,NULL,args,env);
        if(error)return audit_fail("spawn",error);
        int failed=0;
        for(unsigned sequence=0;sequence<2;++sequence){
            union audit_buffer buffer={0};
            kern_return_t kr=mach_msg(&buffer.message.header,MACH_RCV_MSG|MACH_RCV_TIMEOUT|
                MACH_RCV_TRAILER_TYPE(MACH_MSG_TRAILER_FORMAT_0)|MACH_RCV_TRAILER_ELEMENTS(MACH_RCV_TRAILER_AUDIT),
                0,sizeof(buffer),receiver,5000,MACH_PORT_NULL);
            if(kr || !valid_audit_message(&buffer,child,role?501:0,sequence,receiver)){
                failed=audit_fail("receive identity",kr?kr:EINVAL);break;
            }
            printf("AUDIT sender pid=%d uid=%d transport=%s verified\n",child,role?501:0,sequence?"mach_msg2":"mach_msg API");
        }
        int status=-1,done=0;
        for(unsigned i=0;i<20;++i){
            pid_t waited=waitpid(child,&status,WNOHANG);
            if(waited==child){done=1;break;}
            if(waited<0 && errno!=EINTR)break;
            usleep(100000);
        }
        if(!done){kill(child,SIGKILL);waitpid(child,&status,0);return audit_fail("child timeout",ETIMEDOUT);}
        if(failed)return 1;
        if(status)return audit_fail("child status",status);
    }
    puts("AUDIT PASS sender-identity");fflush(stdout);return 0;
}
