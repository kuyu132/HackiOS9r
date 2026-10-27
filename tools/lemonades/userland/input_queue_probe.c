/* QEMU-only diagnostic root: synthetic writes through the legacy endpoint,
 * checks the actual new kernel device. No hardware or complete iOS assertion. */
#include <sys/lemonades_input.h>
#include <sys/redwood_input.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stddef.h>
#include <sys/select.h>
#include <sys/wait.h>
_Static_assert(sizeof(struct lemonades_input_record)==120,"snapshot ABI");
_Static_assert(offsetof(struct lemonades_input_record,x)==40,"snapshot offsets");
static volatile sig_atomic_t interrupted;
static void interrupt_read(int sig){(void)sig;interrupted=1;}
static int write_touch(int fd,unsigned type,unsigned x)
{
    struct redwood_touch t={0,type,0,x,x};
    return write(fd,&t,sizeof(t))==(ssize_t)sizeof(t);
}
static int ready(int fd,unsigned milliseconds)
{
    fd_set set;FD_ZERO(&set);FD_SET(fd,&set);
    struct timeval timeout={milliseconds/1000,(milliseconds%1000)*1000};
    int result=select(fd+1,&set,NULL,NULL,&timeout);
    return result>0 && !FD_ISSET(fd,&set)?-2:result;
}
#define REQUIRE(test,why) do {if(!(test)){failure=why;goto done;}}while(0)
int main(void)
{
    setbuf(stdout,NULL);puts("INPUT QUEUE BEGIN kernel-contract synthetic");
    const char *failure=NULL;int fd=-1,writer=-1,other=-1,down=0;
    struct lemonades_input_record r={0};pid_t wake_child=-1;
    fd=open(LEMONADES_INPUT_DEVICE,O_RDONLY|O_NONBLOCK);
    REQUIRE(fd>=0 && fd<FD_SETSIZE,"open");
    REQUIRE(ready(fd,0)==1,"open snapshot readiness");
    REQUIRE(read(fd,&r,sizeof(r))==sizeof(r) && r.version==1 && r.sequence &&
        (r.flags&LEMONADES_INPUT_OPEN) && !r.active && !r.buttons,"initial idle snapshot");
    REQUIRE(read(fd,&r,0)==0,"zero read");
    errno=0;REQUIRE(read(fd,&r,sizeof(r)-1)==-1 && errno==EINVAL,"short buffer");
    errno=0;REQUIRE(read(fd,&r,sizeof(r))==-1 && errno==EAGAIN,"nonblocking empty");
    REQUIRE(ready(fd,50)==0,"empty select must sleep");
    other=open(LEMONADES_INPUT_DEVICE,O_RDONLY|O_NONBLOCK);
    REQUIRE(other==-1 && errno==EBUSY,"exclusive open");
    other=open(LEMONADES_INPUT_DEVICE,O_RDWR|O_NONBLOCK);
    REQUIRE(other==-1 && errno==EACCES,"read-only node");
    struct sigaction action={0};action.sa_handler=interrupt_read;sigemptyset(&action.sa_mask);
    REQUIRE(!sigaction(SIGALRM,&action,NULL) && !fcntl(fd,F_SETFL,0),"signal setup");
    alarm(1);errno=0;ssize_t n=read(fd,&r,sizeof(r));int saved_errno=errno;alarm(0);
    REQUIRE(n==-1 && saved_errno==EINTR && interrupted,"interruptible blocking read");
    REQUIRE(!fcntl(fd,F_SETFL,O_NONBLOCK),"restore nonblocking");
    interrupted=0;alarm(1);errno=0;n=ready(fd,5000);saved_errno=errno;alarm(0);
    REQUIRE(n==-1 && saved_errno==EINTR && interrupted,"interruptible select");
    writer=open(REDWOOD_TOUCH_DEVICE,O_WRONLY);REQUIRE(writer>=0,"synthetic writer");
    wake_child=fork();REQUIRE(wake_child>=0,"wake child");
    if(!wake_child){close(fd);usleep(100000);_exit(write_touch(writer,REDWOOD_TOUCH_DOWN,42)?0:1);}
    REQUIRE(ready(fd,2000)==1,"delayed writer select wakeup");down=1;
    int child_status;REQUIRE(waitpid(wake_child,&child_status,0)==wake_child && child_status==0,"wake child exit");wake_child=-1;
    errno=0;REQUIRE(read(fd,(void *)(uintptr_t)1,sizeof(r))==-1 && errno==EFAULT,"copyout fault");
    REQUIRE(ready(fd,0)==1,"copyout resync readiness");
    REQUIRE(read(fd,&r,sizeof(r))==sizeof(r) && r.active==1 && r.x[0]==42 &&
        r.dropped>=1 && (r.flags&LEMONADES_INPUT_READ_FAULT) && (r.flags&LEMONADES_INPUT_SYNTHETIC),"fault recovery");
    uint64_t previous=r.sequence,dropped=r.dropped;
    for(unsigned i=0;i<1000;i++)REQUIRE(write_touch(writer,REDWOOD_TOUCH_MOVE,i),"overflow write");
    REQUIRE(read(fd,&r,sizeof(r))==sizeof(r) && (r.flags&LEMONADES_INPUT_OVERFLOW) &&
        r.sequence>previous+1 && r.dropped>dropped && r.active==1,"overflow notification");
    unsigned records=1;
    while((n=read(fd,&r,sizeof(r)))==(ssize_t)sizeof(r))REQUIRE(++records<=64,"bounded queue");
    REQUIRE(n==-1 && errno==EAGAIN && r.x[0]==999,"latest full state");
    REQUIRE(ready(fd,50)==0,"drained select must sleep");
    /* Leave a select registration, close, reopen: no stale waitq linkage. */
    close(fd);fd=open(LEMONADES_INPUT_DEVICE,O_RDONLY|O_NONBLOCK);REQUIRE(fd>=0,"reopen");
    REQUIRE(ready(fd,0)==1,"reopen snapshot readiness");
    REQUIRE(read(fd,&r,sizeof(r))==sizeof(r) && (r.flags&LEMONADES_INPUT_OPEN) &&
        r.active==1 && r.x[0]==999,"reopen active snapshot");
    REQUIRE(write_touch(writer,REDWOOD_TOUCH_UP,999),"up write");down=0;
    REQUIRE(read(fd,&r,sizeof(r))==sizeof(r) && !r.active,"up snapshot");
    printf("INPUT QUEUE observed sequence=%llu dropped=%llu records-after-overflow=%u\n",
        (unsigned long long)r.sequence,(unsigned long long)r.dropped,records);
done:
    alarm(0);
    if(wake_child>1){kill(wake_child,SIGKILL);waitpid(wake_child,NULL,0);}
    if(down && writer>=0)(void)write_touch(writer,REDWOOD_TOUCH_UP,0);
    if(other>=0)close(other);if(writer>=0)close(writer);if(fd>=0)close(fd);
    if(failure){printf("INPUT QUEUE FAIL %s errno=%d\n",failure,errno);return 1;}
    puts("INPUT QUEUE PASS select-wakeup");
    puts("INPUT QUEUE PASS kernel-contract");return 0;
}
