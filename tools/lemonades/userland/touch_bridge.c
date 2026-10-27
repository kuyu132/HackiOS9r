/* One process owns one queue/HID session. launchd restarts failed sessions;
 * old callbacks, Mach rights and input fd die with the old process. */
#include "hid_client_abi.h"
#include "hid_stream.h"
#include <mach/mach_time.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/select.h>
#define STATUS "/private/var/run/lemonades-touch-bridge.status"
static CFDictionaryRef properties;
static atomic_bool opened,reset;
static volatile sig_atomic_t stopping;
static unsigned frames,waits,input_wakes,control_wakes,built_in;
static int wake_read=-1;
static volatile sig_atomic_t wake_write=-1;
/* Nonblocking self-pipe closes the check/sleep race for signals and callbacks.
 * Both ends live until process exit; callbacks never write a recycled fd. */
static void wake_main(void)
{
    int saved=errno;char byte=1;
    if(wake_write>=0)(void)write(wake_write,&byte,1);
    errno=saved;
}
static void stop(int sig){(void)sig;stopping=1;wake_main();}
static int wait_input(int input)
{
    fd_set read_set;FD_ZERO(&read_set);FD_SET(input,&read_set);FD_SET(wake_read,&read_set);
    int highest=input>wake_read?input:wake_read;
    waits++;
    int ready=select(highest+1,&read_set,NULL,NULL,NULL);
    if(ready<0)return errno==EINTR?0:-1;
    if(FD_ISSET(input,&read_set))input_wakes++;
    if(FD_ISSET(wake_read,&read_set)){
        char buffer[128];control_wakes++;
        while(read(wake_read,buffer,sizeof(buffer))>0){}
    }
    return 0;
}
static void watchdog(int sig){(void)sig;_exit(stopping?0:75);}
static void disconnected(void *target,void *refcon,void *sender)
{(void)target;(void)refcon;(void)sender;atomic_store(&reset,true);atomic_store(&opened,false);wake_main();}
static CFTypeRef copy_property(void *target,void *refcon,Service service,CFStringRef key)
{
    (void)target;(void)refcon;(void)service;
    CFTypeRef value=key?CFDictionaryGetValue(properties,key):NULL;
    return value?CFRetain(value):NULL;
}
static Boolean set_property(void *target,void *refcon,Service service,CFStringRef key,CFTypeRef value)
{
    (void)target;(void)refcon;(void)service;
    if(key && value && CFEqual(key,CFSTR("DeviceOpenedByEventSystem")) && CFGetTypeID(value)==CFBooleanGetTypeID()){
        atomic_store(&opened,CFBooleanGetValue(value));wake_main();return true;
    }
    return false; /* Controller power/wake settings are not implemented. */
}
static void notification(void *target,void *refcon,Service service,uint32_t type,CFDictionaryRef value)
{(void)target;(void)refcon;(void)service;(void)type;(void)value;}
static const struct callbacks_v2 callbacks={.version=2,.notification=notification,
    .copy_property=copy_property,.set_property=set_property};
static int send_frame(void *context,const struct lemonades_hid_frame *frame)
{
    if(atomic_load(&reset) || !atomic_load(&opened))return 0;
    IOHIDEventRef event=lemonades_hid_create_event(frame,built_in);
    if(!event)return 0;
    alarm(5);
    Boolean accepted=IOHIDVirtualServiceClientDispatchEvent((Service)context,event);
    alarm(0);CFRelease(event);
    if(!accepted || atomic_load(&reset))return 0;
    frames++;return 1;
}
static int publish(uint64_t id)
{
    char temporary[128],text[128];
    snprintf(temporary,sizeof(temporary),STATUS".%d",getpid());
    int fd=open(temporary,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
    if(fd<0)return -1;
    int size=snprintf(text,sizeof(text),"%d %llu\n",getpid(),(unsigned long long)id);
    int good=write(fd,text,size)==size;close(fd);
    if(good)good=rename(temporary,STATUS)==0;
    if(!good)unlink(temporary);
    return good?0:-1;
}
int main(int argc,char **argv)
{
    setbuf(stdout,NULL);
    bool allow_synthetic=argc>=2 && !strcmp(argv[1],"--allow-synthetic");
#ifdef TEST_INTEGRATED_TOUCH
    /* Available only in an explicitly labelled test build. Never infer this
     * identity from a boot argument or merely from SYNTHETIC being absent. */
    built_in=argc==3 && allow_synthetic && !strcmp(argv[2],"--test-integrated");
    if(argc==3 && !built_in)return 64;
#else
    if(argc>2)return 64;
#endif
    if(argc>3 || (argc>1 && !allow_synthetic))return 64;
    int wake[2];
    if(pipe(wake))return 75;
    if(wake[0]>=FD_SETSIZE || wake[1]>=FD_SETSIZE || fcntl(wake[0],F_SETFL,O_NONBLOCK) || fcntl(wake[1],F_SETFL,O_NONBLOCK))return 75;
    wake_read=wake[0];wake_write=wake[1];
    struct sigaction action={0};sigemptyset(&action.sa_mask);
    action.sa_handler=stop;
    if(sigaction(SIGTERM,&action,NULL) || sigaction(SIGINT,&action,NULL))return 75;
    action.sa_handler=watchdog;if(sigaction(SIGALRM,&action,NULL))return 75;
    int result=75,input=-1;bool published=false;
    Client client=NULL;Service service=NULL;
    struct lemonades_hid_stream stream={0};
    dispatch_queue_t queue=dispatch_queue_create("lemonades.touch.provider",NULL);
    properties=lemonades_hid_properties(built_in?CFSTR("Lemonades TEST simulated integrated touch"):CFSTR("Lemonades queue bridge (Virtual)"),built_in);
    printf("BRIDGE START pid=%d synthetic_allowed=%d\n",getpid(),allow_synthetic);
    printf("BRIDGE PROFILE pid=%d built_in=%u simulated=%u transport=Virtual\n",getpid(),built_in,built_in);
    if(!queue || !properties)goto done;
    alarm(15);
    client=IOHIDEventSystemClientCreateWithType(NULL,4,NULL);
    if(!client)goto done;
    IOHIDEventSystemClientRegisterResetCallback(client,disconnected,NULL,NULL);
    IOHIDEventSystemClientScheduleWithDispatchQueue(client,queue);
    service=IOHIDVirtualServiceClientCreateWithCallbacks(client,properties,&callbacks,NULL,NULL);
    if(!service)goto done;
    for(unsigned i=0;i<80 && !stopping && !atomic_load(&reset) && !atomic_load(&opened);i++)usleep(100000);
    if(stopping || atomic_load(&reset) || !atomic_load(&opened))goto done;
    input=open(LEMONADES_INPUT_DEVICE,O_RDONLY|O_NONBLOCK);
    if(input<0 || input>=FD_SETSIZE)goto done;
    alarm(0);
    while(!stopping && !atomic_load(&reset) && atomic_load(&opened)){
        struct lemonades_input_record record;
        ssize_t n=read(input,&record,sizeof(record));
        if(n<0 && errno==EINTR)continue;
        if(n<0 && errno==EAGAIN){
            if(wait_input(input)){printf("BRIDGE select error errno=%d\n",errno);goto done;}
            continue;
        }
        if(n!=sizeof(record)){printf("BRIDGE input error bytes=%ld errno=%d\n",(long)n,errno);goto done;}
        if(!allow_synthetic && (record.flags&LEMONADES_INPUT_SYNTHETIC)){
            puts("BRIDGE stopped: synthetic input rejected");result=0;goto done;
        }
        if(lemonades_hid_consume(&stream,&record,send_frame,service)){
            puts("BRIDGE session retired: invalid snapshot or uncertain delivery");goto done;
        }
        if(!published){
            uint64_t id=lemonades_hid_service_id(service);
            if(!id || publish(id))goto done;
            published=true;printf("BRIDGE READY pid=%d service=%llu\n",getpid(),(unsigned long long)id);
        }
    }
    if(stopping)result=0;
done:
    alarm(5);
    if(service && !stream.poisoned && !atomic_load(&reset) && atomic_load(&opened)){
        struct lemonades_hid_state next;struct lemonades_hid_frame release;
        if(lemonades_hid_release_all(&stream.touch,mach_absolute_time(),&next,&release) ||
           (release.count && !send_frame(service,&release)))result=75;
    }
    alarm(5);
    if(service)IOHIDVirtualServiceClientRemove(service);
    if(input>=0)close(input);
    if(published)unlink(STATUS);
    if(stopping)result=0;
    printf("BRIDGE WAIT pid=%d waits=%u input_wakes=%u control_wakes=%u\n",getpid(),waits,input_wakes,control_wakes);
    printf("BRIDGE EXIT pid=%d status=%d frames=%u reset=%d\n",getpid(),result,frames,atomic_load(&reset));
    /* Process exit retires all async callback contexts. No reuse after reset. */
    return result;
}
