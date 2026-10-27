/* Original FSEvents client API, linked from the pinned iOS private framework.
 * ABI/flags match the Apple SDK FSEvents.h; only disposable guest files change. */
#include <CoreFoundation/CoreFoundation.h>
#include <dispatch/dispatch.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <spawn.h>
#include <signal.h>
#include <errno.h>
typedef struct __FSEventStream *FSEventStreamRef;
typedef const struct __FSEventStream *ConstFSEventStreamRef;
typedef uint32_t FSEventStreamEventFlags;
typedef uint64_t FSEventStreamEventId;
typedef struct {
    CFIndex version;void *info;CFAllocatorRetainCallBack retain;
    CFAllocatorReleaseCallBack release;CFAllocatorCopyDescriptionCallBack copyDescription;
} FSEventStreamContext;
typedef void (*FSEventStreamCallback)(ConstFSEventStreamRef,void *,size_t,void *,const uint32_t *,const uint64_t *);
extern FSEventStreamRef FSEventStreamCreate(CFAllocatorRef,FSEventStreamCallback,FSEventStreamContext *,CFArrayRef,uint64_t,CFTimeInterval,uint32_t);
extern void FSEventStreamSetDispatchQueue(FSEventStreamRef,dispatch_queue_t);
extern Boolean FSEventStreamStart(FSEventStreamRef);
extern void FSEventStreamStop(FSEventStreamRef);
extern void FSEventStreamInvalidate(FSEventStreamRef);
extern void FSEventStreamRelease(FSEventStreamRef);
struct observation {char file[256];dispatch_semaphore_t done;uint32_t flags;uint64_t id;int cfpaths;uint32_t required;};
static void received(ConstFSEventStreamRef stream,void *opaque,size_t count,void *paths,const uint32_t *flags,const uint64_t *ids)
{
    (void)stream;struct observation *seen=opaque;char **names=paths;
    for(size_t i=0;i<count;++i){
        char converted[1024];const char *name;
        if(seen->cfpaths){
            if(i>=(size_t)CFArrayGetCount(paths))continue;
            CFTypeRef value=CFArrayGetValueAtIndex(paths,(CFIndex)i);
            if(CFGetTypeID(value)!=CFStringGetTypeID() || !CFStringGetCString(value,converted,sizeof(converted),kCFStringEncodingUTF8))continue;
            name=converted;
        }else name=names[i];
        printf("FSEVENTS event path=%s flags=0x%x id=%llu\n",name,flags[i],(unsigned long long)ids[i]);
        uint32_t required=seen->required?seen->required:0x10100;
        if(!strcmp(name,seen->file) && (flags[i]&required)==required &&
           !(flags[i]&0xf) && ids[i] && ids[i]!=UINT64_MAX){
            seen->flags=flags[i];seen->id=ids[i];dispatch_semaphore_signal(seen->done);
        }
    }
    fflush(stdout);
}
static void drain(void *unused){(void)unused;}
static void expect_directory_deletion(void *opaque)
{
    struct observation *seen=opaque;
    seen->required=0x20200;seen->flags=0;seen->id=0;
    while(dispatch_semaphore_wait(seen->done,DISPATCH_TIME_NOW)==0){}
}
static int change_directory_in_child(const char *operation,char *path)
{
    char *args[]={"/bin/fsevents_probe",(char *)operation,path,NULL};
    char *env[]={"PATH=/bin:/usr/bin",NULL};pid_t child=-1;
    if(posix_spawn(&child,args[0],NULL,NULL,args,env))return 1;
    int status=-1;
    for(unsigned i=0;i<40;++i){
        pid_t result=waitpid(child,&status,WNOHANG);
        if(result==child){printf("FSEVENTS producer pid=%d operation=%s status=%d\n",child,operation,status);return status!=0;}
        if(result<0 && errno!=EINTR)break;
        usleep(250000);
    }
    kill(child,SIGKILL);waitpid(child,&status,0);return 1;
}
static int run_case(int directory_delete)
{
    const char *label=directory_delete?"directory-delete":"file-create";
    printf("FSEVENTS BEGIN %s\n",label);fflush(stdout);
    char directory[]="/private/var/tmp/lemonades-events-XXXXXX";
    if(!mkdtemp(directory)){puts("FSEVENTS FAIL mkdir");return 1;}
    struct observation seen={0};snprintf(seen.file,sizeof(seen.file),"%s/created",directory);
    seen.cfpaths=directory_delete;seen.required=directory_delete?0x20100:0x10100;
    seen.done=dispatch_semaphore_create(0);
    CFStringRef path=CFStringCreateWithCString(NULL,directory,kCFStringEncodingUTF8);
    CFArrayRef paths=CFArrayCreate(NULL,(const void **)&path,1,&kCFTypeArrayCallBacks);
    FSEventStreamContext context={0,&seen,NULL,NULL,NULL};
    /* Directory case uses CFTypes | IgnoreSelf | FileEvents, matching the
     * observed CoreFoundation directory-deletion stream options. */
    FSEventStreamRef stream=FSEventStreamCreate(NULL,received,&context,paths,UINT64_MAX,.05,directory_delete?0x19:0x12);
    CFRelease(paths);CFRelease(path);
    dispatch_queue_t queue=dispatch_queue_create("net.hackios9r.fsevents",DISPATCH_QUEUE_SERIAL);
    int ok=0,started=0;
    if(!stream){puts("FSEVENTS FAIL create stream");goto finish;}
    FSEventStreamSetDispatchQueue(stream,queue);
    started=FSEventStreamStart(stream);
    if(!started){puts("FSEVENTS FAIL start stream");goto finish;}
    if(directory_delete){
        if(change_directory_in_child("mkdir",seen.file)){puts("FSEVENTS FAIL prepare directory");goto finish;}
        /* Wait for actual observation before deleting: a short-lived directory
         * can have its creation and removal coalesced by the event service. */
        if(dispatch_semaphore_wait(seen.done,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC))){
            puts("FSEVENTS FAIL directory creation callback timeout");goto finish;
        }
        puts("FSEVENTS directory creation observed before deletion");fflush(stdout);
        dispatch_sync_f(queue,&seen,expect_directory_deletion);
        if(change_directory_in_child("rmdir",seen.file)){puts("FSEVENTS FAIL delete directory");goto finish;}
    }else{
        int fd=open(seen.file,O_CREAT|O_EXCL|O_WRONLY,0600);
        if(fd<0){puts("FSEVENTS FAIL create file");goto finish;}
        int written=write(fd,"change",6)==6;int closed=close(fd)==0;
        if(!written || !closed){puts("FSEVENTS FAIL write file");goto finish;}
    }
    ok=dispatch_semaphore_wait(seen.done,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC))==0;
    if(!ok)puts("FSEVENTS FAIL callback timeout");
finish:
    if(stream){if(started)FSEventStreamStop(stream);FSEventStreamInvalidate(stream);}
    dispatch_sync_f(queue,NULL,drain);
    if(stream)FSEventStreamRelease(stream);
    if(directory_delete)rmdir(seen.file);else unlink(seen.file);rmdir(directory);
    if(ok && seen.id)printf("FSEVENTS PASS %s\n",label);
    dispatch_release(queue);dispatch_release(seen.done);fflush(stdout);return ok?0:1;
}
int main(int argc,char **argv)
{
    if(argc==3){
        if(!strcmp(argv[1],"mkdir"))return mkdir(argv[2],0700)?1:0;
        if(!strcmp(argv[1],"rmdir"))return rmdir(argv[2])?1:0;
        return 2;
    }
    if(argc!=1)return 2;
    return run_case(0) || run_case(1);
}
