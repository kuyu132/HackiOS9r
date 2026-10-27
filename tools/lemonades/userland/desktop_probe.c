/* Query the original HID event service. No injected devices or events.
 * Opaque API types; exports verified in the pinned iOS 16.5 IOKit.tbd. */
#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <mach/mach_time.h>
#include <mach/mach.h>
typedef struct __IOHIDEventSystemClient *IOHIDEventSystemClientRef;
extern IOHIDEventSystemClientRef IOHIDEventSystemClientCreate(CFAllocatorRef);
extern CFArrayRef IOHIDEventSystemClientCopyServices(IOHIDEventSystemClientRef);
extern CFTypeRef IOHIDEventSystemClientCopyProperty(IOHIDEventSystemClientRef,CFStringRef);
extern kern_return_t bootstrap_look_up2(mach_port_t,const char *,mach_port_t *,pid_t,uint64_t);
static void report_connection(IOHIDEventSystemClientRef client)
{
    /* The pinned client's Refresh uses lookup flags=8. Compare with an
     * ordinary lookup without modifying its connection or bypassing policy. */
    for(unsigned i=0;i<2;i++){
        mach_port_t port=MACH_PORT_NULL;uint64_t flags=i?8:0;
        kern_return_t kr=bootstrap_look_up2(bootstrap_port,"com.apple.iohideventsystem",&port,0,flags);
        printf("DESKTOP HID lookup flags=%llu kr=%d port_valid=%d\n",
               (unsigned long long)flags,kr,MACH_PORT_VALID(port));
        if(MACH_PORT_VALID(port))mach_port_deallocate(mach_task_self(),port);
    }
    printf("DESKTOP HID client_nonnull=%d\n",client!=NULL);
    if(client){
        CFStringRef description=CFCopyDescription(client);char text[2048];
        if(description){
            if(CFStringGetCString(description,text,sizeof(text),kCFStringEncodingUTF8))
                printf("DESKTOP HID client_description=%s\n",text);
            else puts("DESKTOP HID client_description exceeds buffer");
            CFRelease(description);
        }
        /* Keys and server branches verified in the pinned IOHIDSession code.
         * Report types/counts, not success, for NULL or unsupported replies. */
        CFStringRef keys[]={CFSTR("HIDIdleTimeMicroseconds"),CFSTR("ServiceRecords"),CFSTR("ClientRecords")};
        const char *names[]={"HIDIdleTimeMicroseconds","ServiceRecords","ClientRecords"};
        for(unsigned i=0;i<3;i++){
            CFTypeRef value=IOHIDEventSystemClientCopyProperty(client,keys[i]);
            const char *type="null";long long number=-1;
            if(value){
                CFTypeID id=CFGetTypeID(value);
                if(id==CFNumberGetTypeID()){
                    int64_t v=-1;type="number";
                    if(CFNumberGetValue(value,kCFNumberSInt64Type,&v))number=v;
                    else type="unreadable-number";
                } else if(id==CFArrayGetTypeID()){type="array";number=CFArrayGetCount(value);}
                else if(id==CFDictionaryGetTypeID()){type="dictionary";number=CFDictionaryGetCount(value);}
                else type="other";
                CFRelease(value);
            }
            printf("DESKTOP HID property=%s type=%s value_or_count=%lld\n",names[i],type,number);
        }
    }
    fflush(stdout);
}
static void report_log(void)
{
    const char *path="/private/var/mobile/Library/Logs/backboard-bringup.log";
    struct stat st;
    if(!stat("/dev/console",&st))printf("DESKTOP console uid=%u gid=%u mode=%o\n",st.st_uid,st.st_gid,st.st_mode&0777);
    if(!stat(path,&st))printf("DESKTOP log uid=%u gid=%u mode=%o size=%lld\n",st.st_uid,st.st_gid,st.st_mode&0777,(long long)st.st_size);
    FILE *f=fopen(path,"r");
    if(!f){puts("DESKTOP log unavailable");return;}
    char line[512];size_t count=0;
    while(count<65536 && fgets(line,sizeof(line),f)){count+=strlen(line);printf("BACKBOARD LOG | %s",line);}
    fclose(f);fflush(stdout);
}
int main(void)
{
    printf("DESKTOP BEGIN hid-services pid=%d uid=%d\n",getpid(),getuid());fflush(stdout);
    /* launchd starts backboard asynchronously. A first failed lookup is not a
     * completed startup observation. Retry fresh connections for at most 20 s;
     * the bootstrap parent separately kills/reaps us if an API blocks. */
    mach_timebase_info_data_t timebase;
    if(mach_timebase_info(&timebase)!=KERN_SUCCESS || !timebase.numer || !timebase.denom){
        puts("DESKTOP FAIL timebase");return 1;
    }
    uint64_t start=mach_absolute_time();
    uint64_t limit=20000000000ULL*timebase.denom/timebase.numer;
    CFIndex count=-1;unsigned attempts=0;
    do {
        IOHIDEventSystemClientRef client=IOHIDEventSystemClientCreate(kCFAllocatorDefault);
        CFArrayRef services=client?IOHIDEventSystemClientCopyServices(client):NULL;
        count=services && CFGetTypeID(services)==CFArrayGetTypeID()?CFArrayGetCount(services):-1;
        if(attempts==0 || attempts==32)report_connection(client);
        if(services)CFRelease(services);
        if(client)CFRelease(client);
        attempts++;
        if(attempts==1 || attempts%4==0 || count>0){
            printf("DESKTOP HID service count=%ld attempt=%u\n",(long)count,attempts);fflush(stdout);
        }
        if(count>0 || mach_absolute_time()-start>=limit)break;
        usleep(250000);
    } while(mach_absolute_time()-start<limit);
    printf("DESKTOP HID observation attempts=%u elapsed_ns=%llu\n",attempts,
           (unsigned long long)((mach_absolute_time()-start)*timebase.numer/timebase.denom));
    report_log();
    if(count<=0){puts("DESKTOP FAIL no HID services");return 1;}
    puts("DESKTOP PASS hid-services");fflush(stdout);return 0;
}
