/* Test launchd-owned bridge in an isolated QEMU root. Only signal a PID whose
 * root-owned status, executable path and visible HID identity agree. */
#include "hid_client_abi.h"
#include <sys/redwood_input.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/lemonades_input.h>
#include <spawn.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <signal.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#ifdef TEST_INTEGRATED_TOUCH
#define EXPECT_BUILT_IN 1
#else
#define EXPECT_BUILT_IN 0
#endif
#define STATUS "/private/var/run/lemonades-touch-bridge.status"
extern int proc_pidpath(int,void *,uint32_t);
#ifdef CHECK_HID_SERVER_RESTART
extern int proc_listallpids(void *,int);
/* Only one exact executable in the isolated test root may be targeted. */
static int server_pid(void)
{
    int pids[1024],found=0,count=proc_listallpids(pids,sizeof(pids));
    if(count<=0 || count>=1024)return 0;
    for(int i=0;i<count;i++){
        char path[1024]={0};
        if(pids[i]>1 && proc_pidpath(pids[i],path,sizeof(path))>0 && !strcmp(path,"/usr/libexec/backboardd")){
            if(found)return 0;found=pids[i];
        }
    }
    return found;
}
#endif
struct sample { uint64_t sender,time; CFIndex identity,touch,range,index; double x,y; int valid; };
static struct sample samples[256];
static unsigned sample_count;
static atomic_bool reset;
static void disconnected(void *a,void *b,void *c)
{(void)a;(void)b;(void)c;atomic_store(&reset,true);}
static void receive(void *a,void *b,void *sender,IOHIDEventRef event)
{
    (void)a;(void)b;(void)sender;
    if(!event || IOHIDEventGetType(event)!=11 || sample_count>=256)return;
    CFArrayRef children=IOHIDEventGetChildren(event);
    if(!children || CFArrayGetCount(children)!=1)return;
    IOHIDEventRef child=(IOHIDEventRef)CFArrayGetValueAtIndex(children,0);
    struct sample *s=&samples[sample_count++];
    s->sender=IOHIDEventGetSenderID(event);s->time=IOHIDEventGetTimeStamp(event);
    s->identity=IOHIDEventGetIntegerValue(child,0xb0006);s->index=IOHIDEventGetIntegerValue(child,0xb0005);
    s->touch=IOHIDEventGetIntegerValue(child,0xb0009);s->range=IOHIDEventGetIntegerValue(child,0xb0008);
    s->x=IOHIDEventGetFloatValue(child,0xb0000);s->y=IOHIDEventGetFloatValue(child,0xb0001);
    s->valid=IOHIDEventGetIntegerValue(event,4)==EXPECT_BUILT_IN && IOHIDEventGetIntegerValue(child,4)==EXPECT_BUILT_IN && IOHIDEventGetType(child)==11 && s->identity>0 && s->time && s->index==1 && isfinite(s->x) && isfinite(s->y);
}
static unsigned cursor(dispatch_queue_t q)
{__block unsigned n;dispatch_sync(q,^{n=sample_count;});return n;}
static int wait_event(dispatch_queue_t q,uint64_t id,unsigned from,int touch,unsigned x,unsigned y)
{
    for(unsigned i=0;i<60 && !atomic_load(&reset);i++){
        __block int found=0;
        dispatch_sync(q,^{
            for(unsigned j=from;j<sample_count;j++){
                const struct sample *s=&samples[j];
                if(s->valid && s->sender==id && s->touch==touch && s->range==touch &&
                   fabs(s->x-x/65535.0)<0.0001 && fabs(s->y-y/65535.0)<0.0001)found=1;
            }
        });
        if(found)return 1;usleep(100000);
    }
    return 0;
}
static int visible(Client client,uint64_t id)
{
    CFArrayRef all=IOHIDEventSystemClientCopyServices(client);
    if(all)CFRelease(all);
    Service service=IOHIDEventSystemClientCopyServiceForRegistryID(client,id);
    if(service){CFRelease(service);return 1;}return 0;
}
static int profile_matches(Client client,uint64_t id)
{
    Service service=IOHIDEventSystemClientCopyServiceForRegistryID(client,id);
    if(!service)return 0;
    CFTypeRef built=IOHIDServiceClientCopyProperty(service,CFSTR("Built-In"));
    CFTypeRef transport=IOHIDServiceClientCopyProperty(service,CFSTR("Transport"));
    int good=built && CFGetTypeID(built)==CFBooleanGetTypeID() &&
        CFBooleanGetValue(built)==EXPECT_BUILT_IN && transport && CFEqual(transport,CFSTR("Virtual"));
    if(built)CFRelease(built);if(transport)CFRelease(transport);CFRelease(service);return good;
}
static int read_ready(int *pid,uint64_t *id)
{
    struct stat st;
    if(lstat(STATUS,&st) || !S_ISREG(st.st_mode) || st.st_uid || (st.st_mode&0777)!=0600 || st.st_size>128)return 0;
    int fd=open(STATUS,O_RDONLY|O_NOFOLLOW);if(fd<0)return 0;
    char text[129]={0},path[1024]={0};ssize_t n=read(fd,text,128);close(fd);
    unsigned long long number=0;int process=0;
    if(n<=0 || sscanf(text,"%d %llu",&process,&number)!=2 || process<=1 || !number ||
       proc_pidpath(process,path,sizeof(path))<=0 || strcmp(path,"/usr/libexec/lemonades-touch-bridge") || kill(process,0))return 0;
    *pid=process;*id=number;return 1;
}
static int wait_ready(Client client,int old_pid,int *pid,uint64_t *id)
{
    for(unsigned i=0;i<300 && !atomic_load(&reset);i++){
        if(read_ready(pid,id) && *pid!=old_pid && visible(client,*id))return 1;
        usleep(100000);
    }
    return 0;
}
static int wait_removed(Client client,uint64_t id)
{
    for(unsigned i=0;i<60;i++){
        if(!visible(client,id)){
            CFTypeRef records=IOHIDEventSystemClientCopyProperty(client,CFSTR("ClientRecords"));
            int live=records && CFGetTypeID(records)==CFArrayGetTypeID() && CFArrayGetCount(records)>0;
            if(records)CFRelease(records);
            if(live && !atomic_load(&reset))return 1;
        }
        usleep(100000);
    }
    return 0;
}
#define REQUIRE(condition,reason) do {if(!(condition)){failure=reason;goto done;}}while(0)
int main(void)
{
    setbuf(stdout,NULL);puts("BRIDGE TEST BEGIN synthetic-supervision");
    const char *failure=NULL;int writer=-1,pid=0,down=0;pid_t policy_child=-1;uint64_t id=0;
    Client observer=NULL;dispatch_queue_t q=dispatch_queue_create("lemonades.bridge.observer",NULL);
    REQUIRE(q,"queue");
    observer=IOHIDEventSystemClientCreateWithType(NULL,1,NULL);REQUIRE(observer,"observer");
    IOHIDEventSystemClientRegisterEventCallback(observer,receive,NULL,NULL);
    IOHIDEventSystemClientRegisterResetCallback(observer,disconnected,NULL,NULL);
    IOHIDEventSystemClientScheduleWithDispatchQueue(observer,q);
    REQUIRE(wait_ready(observer,0,&pid,&id),"initial ready or executable identity");
    REQUIRE(profile_matches(observer,id),"service profile");
    printf("BRIDGE TEST profile built_in=%d transport=Virtual\n",EXPECT_BUILT_IN);
    printf("BRIDGE TEST initial pid=%d service=%llu\n",pid,(unsigned long long)id);
    writer=open(REDWOOD_TOUCH_DEVICE,O_WRONLY);REQUIRE(writer>=0,"writer");
    struct redwood_touch record={0,REDWOOD_TOUCH_DOWN,0,1200,2400};
    unsigned from=cursor(q);
    REQUIRE(write(writer,&record,sizeof(record))==sizeof(record),"down write");down=1;
    REQUIRE(wait_event(q,id,from,1,1200,2400),"daemon event delivery");
    puts("BRIDGE TEST PASS device-event-profile");
    puts("BRIDGE TEST PASS daemon-delivery");
    int old_pid=pid;uint64_t old_id=id;
    from=cursor(q);REQUIRE(!kill(pid,SIGKILL),"fault injection");pid=0;
    REQUIRE(wait_ready(observer,old_pid,&pid,&id) && id!=old_id,"launchd restart");
    REQUIRE(profile_matches(observer,id),"restarted service profile");
    REQUIRE(wait_removed(observer,old_id),"old service retirement");
    REQUIRE(wait_event(q,id,from,1,1200,2400),"held-touch recovery");
    printf("BRIDGE TEST restarted pid=%d service=%llu\n",pid,(unsigned long long)id);
    puts("BRIDGE TEST PASS restart-held-contact");
    unsigned final_x=1200,final_y=2400;
#ifdef CHECK_HID_SERVER_RESTART
    int old_server=server_pid();
    REQUIRE(old_server>1,"unique HID server executable");
    printf("BRIDGE SERVER fault server=%d bridge=%d probe=%d\n",old_server,pid,getpid());
    old_pid=pid;old_id=id;from=cursor(q);
    REQUIRE(!kill(old_server,SIGKILL),"HID server fault injection");
    for(unsigned i=0;i<100 && !atomic_load(&reset);i++)usleep(100000);
    REQUIRE(atomic_load(&reset),"observer reset notification");
    /* The pinned client reconnects on refresh. Keep the subscription and
     * record history; a second unexpected reset fails the remaining test. */
    atomic_store(&reset,false);
    REQUIRE(wait_ready(observer,old_pid,&pid,&id),"bridge restart after server death");
    REQUIRE(profile_matches(observer,id),"server recovery service profile");
    int new_server=server_pid();
    REQUIRE(new_server>1 && new_server!=old_server,"new HID server executable");
    REQUIRE(wait_event(q,id,from,1,1200,2400),"server restart held-contact delivery");
    if(id!=old_id)REQUIRE(wait_removed(observer,old_id),"old server service retirement");
    final_x=1300;final_y=2500;from=cursor(q);
    record.type=REDWOOD_TOUCH_MOVE;record.x=final_x;record.y=final_y;
    REQUIRE(write(writer,&record,sizeof(record))==sizeof(record),"post-server-restart move");
    REQUIRE(wait_event(q,id,from,1,final_x,final_y),"post-server-restart delivery");
    printf("BRIDGE SERVER recovered server=%d bridge=%d service=%llu\n",new_server,pid,(unsigned long long)id);
    puts("BRIDGE TEST PASS server-restart-held-contact");
#endif
    from=cursor(q);REQUIRE(!kill(pid,SIGTERM),"graceful stop request");
    REQUIRE(wait_event(q,id,from,0,final_x,final_y),"shutdown release");
    REQUIRE(wait_removed(observer,id),"shutdown removal");
    for(unsigned i=0;i<50;i++){
        int other_pid;uint64_t other_id;
        REQUIRE(!read_ready(&other_pid,&other_id),"unexpected restart after clean stop");
        usleep(100000);
    }
    pid=0;puts("BRIDGE TEST PASS graceful-release-stop");
    /* Synthetic is sticky for this boot. A separately spawned default daemon
     * must reject the held contact, exit cleanly and relinquish its queue. */
    from=cursor(q);
    char *args[]={"/usr/libexec/lemonades-touch-bridge",NULL};
    char *environment[]={"PATH=/usr/bin:/bin","HOME=/var/root",NULL};
    REQUIRE(!posix_spawn(&policy_child,args[0],NULL,NULL,args,environment),"default daemon spawn");
    int status=-1,finished=0;
    for(unsigned i=0;i<200;i++){
        pid_t waited=waitpid(policy_child,&status,WNOHANG);
        if(waited==policy_child){finished=1;policy_child=-1;break;}
        if(waited<0 && errno!=EINTR)break;
        usleep(100000);
    }
    REQUIRE(finished && WIFEXITED(status) && WEXITSTATUS(status)==0,"default synthetic refusal exit");
    int unexpected_pid;uint64_t unexpected_id;
    REQUIRE(!read_ready(&unexpected_pid,&unexpected_id) && cursor(q)==from,"default synthetic refusal emitted events");
    int released=open(LEMONADES_INPUT_DEVICE,O_RDONLY|O_NONBLOCK);
    REQUIRE(released>=0,"default queue release");close(released);
    puts("BRIDGE TEST PASS synthetic-default-rejected");
done:
    if(policy_child>1){kill(policy_child,SIGKILL);waitpid(policy_child,NULL,0);}
    if(down && writer>=0){struct redwood_touch up={0,REDWOOD_TOUCH_UP,0,1200,2400};(void)write(writer,&up,sizeof(up));}
    if(writer>=0)close(writer);
    if(failure){
        int verified_pid;uint64_t verified_id;
        if(pid>1 && read_ready(&verified_pid,&verified_id) && verified_pid==pid && verified_id==id)kill(pid,SIGTERM);
    }
    if(observer){IOHIDEventSystemClientUnregisterEventCallback(observer);IOHIDEventSystemClientUnscheduleFromDispatchQueue(observer,q);}
    if(q)dispatch_sync(q,^{});
    if(observer)CFRelease(observer);
    if(failure){printf("BRIDGE TEST FAIL %s errno=%d\n",failure,errno);return 1;}
    return 0;
}
