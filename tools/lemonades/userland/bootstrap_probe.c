/* A real Apple launchd job: checks service check-in and lookup across its IPC. */
#include <mach/mach.h>
#include <stdio.h>
#include <unistd.h>
#include <spawn.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
#include <grp.h>
#include <sys/wait.h>
#include <stdlib.h>
#ifdef CHECK_CORE_SERVICES
#include <notify.h>
#endif
/* Fixed XNU libsyscall/wrappers/spawn/spawn_private.h. */
extern int posix_spawnattr_set_persona_np(const posix_spawnattr_t *,uid_t,uint32_t);
extern int posix_spawnattr_set_persona_uid_np(const posix_spawnattr_t *,uid_t);
extern int audit_probe_child(const char *);
extern int check_audit_trailers(mach_port_t);
#ifdef CHECK_PREFERENCES
extern int preferences_probe_child(const char *,const char *);
extern int check_preferences(void);
#endif
#ifdef CHECK_USERMANAGER
#include <CoreFoundation/CoreFoundation.h>
#include <sys/stat.h>
extern int kpersona_find_by_type(int,uid_t *,size_t *);
extern int check_ramfs_rename(void);
extern int muser_probe_child(void);
static int failed(const char *,kern_return_t);
struct persona_ids {uid_t values[64];size_t count;};
static int collect_persona_ids(CFTypeRef value,struct persona_ids *ids,unsigned depth)
{
    if (depth>16) return 0;
    if (CFGetTypeID(value)==CFDictionaryGetTypeID()) {
        CFDictionaryRef dict=value;
        CFTypeRef id=CFDictionaryGetValue(dict,CFSTR("UserPersonaID"));
        if (id) {
            int64_t number=-1;
            if (CFGetTypeID(id)!=CFNumberGetTypeID() || !CFNumberGetValue(id,kCFNumberSInt64Type,&number) ||
                number<0 || number>UINT32_MAX || ids->count==64) return 0;
            for (size_t i=0;i<ids->count;++i) if (ids->values[i]==(uid_t)number) return 0;
            ids->values[ids->count++]=(uid_t)number;
        }
        CFIndex count=CFDictionaryGetCount(dict);
        if (count>256) return 0;
        const void *values[256];CFDictionaryGetKeysAndValues(dict,NULL,values);
        for (CFIndex i=0;i<count;++i) if (!collect_persona_ids(values[i],ids,depth+1)) return 0;
    } else if (CFGetTypeID(value)==CFArrayGetTypeID()) {
        CFIndex count=CFArrayGetCount(value);
        if (count>256) return 0;
        for (CFIndex i=0;i<count;++i)
            if (!collect_persona_ids(CFArrayGetValueAtIndex(value,i),ids,depth+1)) return 0;
    } else if (CFGetTypeID(value)==CFDataGetTypeID()) {
        /* v1 UserPersonaDictionary values are nested binary plists, observed
         * from the original daemon's saved RAM-volume manifest. */
        CFIndex size=CFDataGetLength(value);
        if (size>=8 && !memcmp(CFDataGetBytePtr(value),"bplist00",8)) {
            if (size>1048576) return 0;
            CFPropertyListRef nested=CFPropertyListCreateWithData(NULL,value,kCFPropertyListImmutable,NULL,NULL);
            if (!nested) return 0;
            int valid=collect_persona_ids(nested,ids,depth+1);CFRelease(nested);
            if (!valid) return 0;
        }
    }
    return 1;
}
static int match_kernel_personas(CFPropertyListRef plist)
{
    struct persona_ids ids={0};
    CFTypeRef version=CFDictionaryGetValue(plist,CFSTR("UsePersonaManifestVersion"));
    int64_t number=-1;
    if (!version || CFGetTypeID(version)!=CFNumberGetTypeID() ||
        !CFNumberGetValue(version,kCFNumberSInt64Type,&number) || number!=1)
        return failed("persona manifest version",EINVAL);
    if (!collect_persona_ids(plist,&ids,0) || !ids.count) {
        CFShow(plist);return failed("persona manifest IDs",EINVAL);
    }
    size_t total=0;unsigned matched[64]={0};
    /* These three types are created by original --init for this fresh single-user boot. */
    for (int type=4;type<=6;++type) {
        uid_t kernel[64];size_t count=64;
        int result=kpersona_find_by_type(type,kernel,&count);
        if (result<=0 || (size_t)result!=count || count>64) return failed("persona manifest kernel query",result<0 ? errno : EINVAL);
        for (size_t i=0;i<count;++i) {
            size_t j=0;for (;j<ids.count && ids.values[j]!=kernel[i];++j) {}
            if (j==ids.count || matched[j]++) return failed("persona manifest kernel mismatch",EINVAL);
        }
        total+=count;
    }
    if (total!=ids.count) return failed("persona manifest extra IDs",EINVAL);
    printf("USERMANAGER PASS manifest-kernel count=%zu\n",total);return 0;
}
static int check_user_state(void)
{
    const char *paths[]={"/private/var/keybags/usersession.kb","/private/var/keybags/persona.kb"};
    for (unsigned i=0;i<2;++i) {
        FILE *file=fopen(paths[i],"rb");struct stat st;
        if (!file) return failed("user state open",errno);
        if (fstat(fileno(file),&st) || !S_ISREG(st.st_mode) || st.st_uid!=0 ||
            (st.st_mode&0022) || st.st_size<=0 || st.st_size>1048576) {
            fclose(file);return failed("user state metadata",EINVAL);
        }
        unsigned char *bytes=malloc((size_t)st.st_size);
        if (!bytes) {fclose(file);return failed("user state allocation",ENOMEM);}
        size_t length=fread(bytes,1,(size_t)st.st_size,file);fclose(file);
        if (length!=(size_t)st.st_size) {free(bytes);return failed("user state read",EIO);}
        CFDataRef data=CFDataCreate(NULL,bytes,(CFIndex)length);free(bytes);
        if (!data) return failed("user state data",ENOMEM);
        CFPropertyListRef plist=CFPropertyListCreateWithData(NULL,data,kCFPropertyListImmutable,NULL,NULL);
        CFRelease(data);
        int valid=plist && CFGetTypeID(plist)==CFDictionaryGetTypeID() && CFDictionaryGetCount(plist)>0;
        if (valid && i==1 && match_kernel_personas(plist)) {CFRelease(plist);return 1;}
        if (plist) CFRelease(plist);
        if (!valid) return failed("user state plist",EINVAL);
        printf("USERMANAGER state-file %s bytes=%zu mode=%o\n",paths[i],length,st.st_mode&0777);
    }
    puts("USERMANAGER PASS state-files");return 0;
}
#endif
/* Apple's servers/bootstrap.h uses const name_t (char[128]) for these names.
 * The iOS SDK omits that header, but libSystem exports both functions. */
extern kern_return_t bootstrap_check_in(mach_port_t,const char *,mach_port_t *);
extern kern_return_t bootstrap_look_up(mach_port_t,const char *,mach_port_t *);
static int failed(const char *stage,kern_return_t result)
{
    printf("BOOTSTRAP FAIL: %s result=%d\n",stage,result);fflush(stdout);return 1;
}
static int check_persona_rejection(void)
{
    pid_t child=fork();
    if (child<0) return failed("credential-fork",errno);
    if (child==0) {
        gid_t group=501;
        if (setgroups(1,&group) || setgid(501) || setuid(501) || getuid()!=501 || geteuid()!=501)
            _exit(failed("credential-drop",errno));
        posix_spawnattr_t attr;
        int error=posix_spawnattr_init(&attr);
        if (!error) error=posix_spawnattr_set_persona_np(&attr,0x7ffffffe,1);
        if (!error) error=posix_spawnattr_set_persona_uid_np(&attr,0);
        if (error) _exit(failed("persona-attributes",error));
        char *args[]={"/bin/bootstrap_probe","forbidden-persona-child",NULL};
        char *env[]={"PATH=/bin:/usr/bin",NULL};
        pid_t spawned=-1;
        error=posix_spawn(&spawned,args[0],NULL,&attr,args,env);
        posix_spawnattr_destroy(&attr);
        if (!error) { int status;waitpid(spawned,&status,0);_exit(failed("missing persona allowed",0)); }
        if (error!=EPERM || getuid()!=501 || geteuid()!=501) _exit(failed("persona-rejection",error));
        puts("PERSONA PASS unentitled-spawn-denied uid=501 errno=1");fflush(stdout);_exit(0);
    }
    int status=-1;
    if (waitpid(child,&status,0)!=child || status!=0) return failed("credential-child",status);
    puts("BOOTSTRAP PASS credentials");return 0;
}
#ifdef CHECK_CORE_SERVICES
static int notify_child(const char *name,const char *text)
{
    int token=-1;uint64_t value=strtoull(text,NULL,10);
    uint32_t result=notify_register_check(name,&token);
    if (result) return failed("notify child register",result);
    result=notify_set_state(token,value);
    if (result) return failed("notify child state",result);
    result=notify_post(name);
    if (result) return failed("notify child post",result);
    result=notify_cancel(token);
    return result ? failed("notify child cancel",result) : 0;
}
static void dump_logd_output(void)
{
    FILE *file=fopen("/private/var/db/diagnostics/bringup.log","r");
    if (!file) {printf("CORE LOGD output unavailable errno=%d\n",errno);return;}
    char buffer[1024];size_t length,total=0;
    puts("CORE LOGD output begin");
    while (total<32768 && (length=fread(buffer,1,sizeof(buffer),file))>0) {
        fwrite(buffer,1,length,stdout);total+=length;
    }
    fclose(file);puts("CORE LOGD output end");fflush(stdout);
}
static int check_notify_service(void)
{
    char name[96];snprintf(name,sizeof(name),"net.hackios9r.notify.%d",getpid());
    int token=-1,changed=0;
    uint32_t result=notify_register_check(name,&token);
    if (result) return failed("notify register",result);
    result=notify_check(token,&changed); /* Consume the initial registration state. */
    if (result) return failed("notify initial check",result);
    pid_t child=-1;
    uint64_t expected=0x3908000000000000ull|(uint32_t)getpid();
    char value[32];snprintf(value,sizeof(value),"%llu",(unsigned long long)expected);
    char *args[]={"/bin/bootstrap_probe","notify-child",name,value,NULL};
    char *env[]={"PATH=/bin:/usr/bin",NULL};
    /* Fresh image: libnotify calls after fork without exec are not supported.
     * notify.h permits false-positive checks; the state comparison is mandatory. */
    int spawn_error=posix_spawn(&child,args[0],NULL,NULL,args,env);
    if (spawn_error) return failed("notify spawn",spawn_error);
    int status=-1;
    if (waitpid(child,&status,0)!=child || status!=0) return failed("notify child",status);
    for (int i=0;i<20;++i) {
        result=notify_check(token,&changed);
        if (result) return failed("notify check",result);
        if (changed) break;
        usleep(50000);
    }
    uint64_t observed=0;
    result=notify_get_state(token,&observed);
    if (result || observed!=expected) return failed("notify cross-process state",result);
    result=notify_cancel(token);
    if (!changed || result) return failed("notify delivery/cancel",result);
    puts("CORE PASS notify-cross-process");fflush(stdout);return 0;
}
#endif
int main(int argc,char **argv)
{
    if(argc==3 && !strcmp(argv[1],"audit-child"))return audit_probe_child(argv[2]);
#ifdef CHECK_PREFERENCES
    if (argc==4 && !strcmp(argv[1],"preferences-child")) return preferences_probe_child(argv[2],argv[3]);
#endif
#ifdef CHECK_USERMANAGER
    if (argc==2 && !strcmp(argv[1],"muser-child")) return muser_probe_child();
#endif
#ifdef CHECK_CORE_SERVICES
    if (argc==4 && !strcmp(argv[1],"notify-child")) return notify_child(argv[2],argv[3]);
#endif
    if (argc==2 && !strcmp(argv[1],"forbidden-persona-child")) return failed("forbidden child executed",getuid());
    mach_port_t receiver=MACH_PORT_NULL,sender=MACH_PORT_NULL,missing=MACH_PORT_NULL;
    mach_port_type_t type=0;
    const char *name="net.hackios9r.bootstrap-probe";
    if (getpid()<=1 || getppid()!=1 || bootstrap_port==MACH_PORT_NULL) return failed("identity",-1);
    printf("BOOTSTRAP BEGIN v1 pid=%d ppid=%d uid=%d euid=%d gid=%d egid=%d\n",
        getpid(),getppid(),getuid(),geteuid(),getgid(),getegid());fflush(stdout);
    if (getuid()!=0 || geteuid()!=0 || getgid()!=0 || getegid()!=0) return failed("configured root job identity",-1);
    kern_return_t kr=bootstrap_check_in(bootstrap_port,name,&receiver);
    if (kr!=KERN_SUCCESS) return failed("check-in",kr);
    kr=mach_port_type(mach_task_self(),receiver,&type);
    if (kr!=KERN_SUCCESS || !(type&MACH_PORT_TYPE_RECEIVE)) return failed("receive-right",kr);
    kr=bootstrap_look_up(bootstrap_port,name,&sender);
    if (kr!=KERN_SUCCESS) return failed("lookup",kr);
    kr=mach_port_type(mach_task_self(),sender,&type);
    if (kr!=KERN_SUCCESS || !(type&MACH_PORT_TYPE_SEND) || sender!=receiver) return failed("send-right",kr);
    kr=bootstrap_look_up(bootstrap_port,"net.hackios9r.not-registered",&missing);
    if (kr!=1102 || missing!=MACH_PORT_NULL) return failed("unknown-service",kr);
    puts("BOOTSTRAP PASS check-in-lookup v1");
    if(check_audit_trailers(receiver))return 1;
    kr=mach_port_deallocate(mach_task_self(),sender);
    if (kr!=KERN_SUCCESS) return failed("release-send",kr);
    kr=mach_port_mod_refs(mach_task_self(),receiver,MACH_PORT_RIGHT_RECEIVE,-1);
    if (kr!=KERN_SUCCESS) return failed("release-receive",kr);
    if (check_persona_rejection()) return 1;
#ifdef CHECK_CORE_SERVICES
    if (check_notify_service()) {dump_logd_output();return 1;}
#endif
#ifdef CHECK_USERMANAGER
    if (check_ramfs_rename()) return 1;
    if (check_user_state()) return 1;
    mach_port_t manager=MACH_PORT_NULL;
    kr=bootstrap_look_up(bootstrap_port,"com.apple.mobile.usermanagerd.xpc",&manager);
    if (kr!=KERN_SUCCESS) return failed("usermanager service lookup",kr);
    mach_port_deallocate(mach_task_self(),manager);
    int ready=0,last_error=0;
    for (unsigned attempt=0;attempt<40;++attempt) {
        uid_t ids[8]={0};size_t count=8;
        int result=kpersona_find_by_type(6,ids,&count);
        /* Apple's libsyscall wrapper returns the count, not syscall success 0. */
        if (result>0 && (size_t)result==count && count<=8) {
            printf("USERMANAGER PASS system-proxy count=%zu first=%u\n",count,ids[0]);ready=1;break;
        }
        last_error=result<0 ? errno : EINVAL;usleep(500000);
    }
#ifdef CHECK_CORE_SERVICES
    dump_logd_output();
#endif
    if (!ready) return failed("usermanager system-proxy unavailable",last_error);
    char *rpc_args[]={"/bin/bootstrap_probe","muser-child",NULL};
    char *rpc_env[]={"PATH=/bin:/usr/bin",NULL};pid_t rpc_child=-1;
    int rpc_error=posix_spawn(&rpc_child,rpc_args[0],NULL,NULL,rpc_args,rpc_env);
    if (rpc_error) return failed("usermanager RPC spawn",rpc_error);
    int rpc_status=-1,rpc_done=0;
    for (unsigned i=0;i<40;++i) {
        pid_t waited=waitpid(rpc_child,&rpc_status,WNOHANG);
        if (waited==rpc_child) {rpc_done=1;break;}
        if (waited<0) break;
        usleep(500000);
    }
    if (!rpc_done) {kill(rpc_child,SIGKILL);waitpid(rpc_child,&rpc_status,0);return failed("usermanager RPC timeout",ETIMEDOUT);}
    FILE *umdlog=fopen("/private/var/logs/usermanagerd.log","r");
    if (umdlog) {
        char buffer[1024];size_t length,total=0;puts("USERMANAGER LOG begin");
        while (total<32768 && (length=fread(buffer,1,sizeof(buffer),umdlog))>0) {fwrite(buffer,1,length,stdout);total+=length;}
        fclose(umdlog);puts("USERMANAGER LOG end");
    }
    if (rpc_status) return failed("usermanager RPC child",rpc_status);
    puts("USERMANAGER PASS muser-rpc");
    char *ns_args[]={"/bin/nsxpc_probe",NULL};pid_t ns_child=-1;
    int ns_error=posix_spawn(&ns_child,ns_args[0],NULL,NULL,ns_args,rpc_env);
    if (ns_error) return failed("NSXPC spawn",ns_error);
    int ns_status=-1,ns_done=0;
    for (unsigned i=0;i<50;++i) {
        pid_t waited=waitpid(ns_child,&ns_status,WNOHANG);
        if (waited==ns_child) {ns_done=1;break;}
        if (waited<0) break;
        usleep(500000);
    }
    if (!ns_done) {kill(ns_child,SIGKILL);waitpid(ns_child,&ns_status,0);return failed("NSXPC timeout",ETIMEDOUT);}
    if (ns_status) return failed("NSXPC child",ns_status);
#endif
#ifdef CHECK_LOCALE
    char *locale_args[]={"/bin/locale_probe",NULL};
    char *locale_env[]={"PATH=/bin:/usr/bin","HOME=/var/root",NULL};
    pid_t locale_child=-1;int locale_status=-1,locale_done=0;
    int locale_error=posix_spawn(&locale_child,locale_args[0],NULL,NULL,locale_args,locale_env);
    if(locale_error)return failed("locale spawn",locale_error);
    for(unsigned i=0;i<40;++i){
        pid_t waited=waitpid(locale_child,&locale_status,WNOHANG);
        if(waited==locale_child){locale_done=1;break;}
        if(waited<0 && errno!=EINTR)break;
        usleep(250000);
    }
    if(!locale_done){kill(locale_child,SIGKILL);waitpid(locale_child,&locale_status,0);return failed("locale timeout",ETIMEDOUT);}
    if(locale_status)return failed("locale child",locale_status);
#endif
#ifdef CHECK_INPUT_QUEUE
    char *queue_args[]={"/bin/input_queue_probe",NULL};
    char *queue_env[]={"PATH=/bin:/usr/bin","HOME=/var/root",NULL};
    pid_t queue_child=-1;int queue_status=-1,queue_done=0;
    int queue_error=posix_spawn(&queue_child,queue_args[0],NULL,NULL,queue_args,queue_env);
    if(queue_error)return failed("input queue spawn",queue_error);
    for(unsigned i=0;i<80;++i){
        pid_t waited=waitpid(queue_child,&queue_status,WNOHANG);
        if(waited==queue_child){queue_done=1;break;}
        if(waited<0 && errno!=EINTR)break;
        usleep(250000);
    }
    if(!queue_done){kill(queue_child,SIGKILL);waitpid(queue_child,&queue_status,0);return failed("input queue timeout",ETIMEDOUT);}
    if(queue_status)return failed("input queue child",queue_status);
#endif
#ifdef CHECK_HID_ENCODING
    char *hid_args[]={"/bin/hid_touch_probe",NULL};
    char *hid_env[]={"PATH=/bin:/usr/bin","HOME=/var/root",NULL};
    pid_t hid_child=-1;int hid_status=-1,hid_done=0;
    int hid_error=posix_spawn(&hid_child,hid_args[0],NULL,NULL,hid_args,hid_env);
    if(hid_error)return failed("HID encoding spawn",hid_error);
    for(unsigned i=0;i<40;++i){
        pid_t waited=waitpid(hid_child,&hid_status,WNOHANG);
        if(waited==hid_child){hid_done=1;break;}
        if(waited<0 && errno!=EINTR)break;
        usleep(250000);
    }
    if(!hid_done){kill(hid_child,SIGKILL);waitpid(hid_child,&hid_status,0);return failed("HID encoding timeout",ETIMEDOUT);}
    if(hid_status)return failed("HID encoding child",hid_status);
#endif
#ifdef CHECK_HID_SERVICE
    char *service_args[]={"/bin/hid_service_probe",NULL};
    char *service_env[]={"PATH=/bin:/usr/bin","HOME=/var/root",NULL};
    pid_t service_child=-1;int service_status=-1,service_done=0;
    int service_error=posix_spawn(&service_child,service_args[0],NULL,NULL,service_args,service_env);
    if(service_error)return failed("HID service spawn",service_error);
    for(unsigned i=0;i<200;++i){
        pid_t waited=waitpid(service_child,&service_status,WNOHANG);
        if(waited==service_child){service_done=1;break;}
        if(waited<0 && errno!=EINTR)break;
        usleep(250000);
    }
    if(!service_done){kill(service_child,SIGKILL);waitpid(service_child,&service_status,0);return failed("HID service timeout",ETIMEDOUT);}
    if(service_status)return failed("HID service child",service_status);
#endif
#ifdef CHECK_TOUCH_BRIDGE
    char *bridge_args[]={"/bin/touch_bridge_probe",NULL};
    char *bridge_env[]={"PATH=/bin:/usr/bin","HOME=/var/root",NULL};
    pid_t bridge_child=-1;int bridge_status=-1,bridge_done=0;
    int bridge_error=posix_spawn(&bridge_child,bridge_args[0],NULL,NULL,bridge_args,bridge_env);
    if(bridge_error)return failed("touch bridge spawn",bridge_error);
    for(unsigned i=0;i<360;++i){
        pid_t waited=waitpid(bridge_child,&bridge_status,WNOHANG);
        if(waited==bridge_child){bridge_done=1;break;}
        if(waited<0 && errno!=EINTR)break;
        usleep(250000);
    }
    if(!bridge_done){kill(bridge_child,SIGKILL);waitpid(bridge_child,&bridge_status,0);return failed("touch bridge timeout",ETIMEDOUT);}
    if(bridge_status)return failed("touch bridge child",bridge_status);
#endif
#ifdef CHECK_BACKBOARD
    char *desktop_args[]={"/bin/desktop_probe",NULL};
    char *desktop_env[]={"PATH=/bin:/usr/bin","HOME=/var/root","OS_ACTIVITY_DT_MODE=YES",NULL};
    pid_t desktop_child=-1;int desktop_status=-1,desktop_done=0;
    int desktop_error=posix_spawn(&desktop_child,desktop_args[0],NULL,NULL,desktop_args,desktop_env);
    if(desktop_error)return failed("desktop spawn",desktop_error);
    for(unsigned i=0;i<120;++i){
        pid_t waited=waitpid(desktop_child,&desktop_status,WNOHANG);
        if(waited==desktop_child){desktop_done=1;break;}
        if(waited<0 && errno!=EINTR)break;
        usleep(250000);
    }
    if(!desktop_done){kill(desktop_child,SIGKILL);waitpid(desktop_child,&desktop_status,0);return failed("desktop timeout",ETIMEDOUT);}
    if(desktop_status)return failed("desktop child",desktop_status);
#endif
#ifdef CHECK_FSEVENTS
    char *fs_args[]={"/bin/fsevents_probe",NULL};
    char *fs_env[]={"PATH=/bin:/usr/bin","HOME=/var/root","OS_ACTIVITY_DT_MODE=YES",NULL};
    pid_t fs_child=-1;int fs_status=-1,fs_done=0;
    int fs_error=posix_spawn(&fs_child,fs_args[0],NULL,NULL,fs_args,fs_env);
    if(fs_error)return failed("FSEvents spawn",fs_error);
    for(unsigned i=0;i<120;++i){
        pid_t waited=waitpid(fs_child,&fs_status,WNOHANG);
        if(waited==fs_child){fs_done=1;break;}
        if(waited<0 && errno!=EINTR)break;
        usleep(250000);
    }
    if(!fs_done){kill(fs_child,SIGKILL);waitpid(fs_child,&fs_status,0);return failed("FSEvents timeout",ETIMEDOUT);}
    if(fs_status)return failed("FSEvents child",fs_status);
#endif
#ifdef CHECK_PREFERENCES
    if (check_preferences()) return failed("preferences integration",1);
#endif
    puts("BOOTSTRAP COMPLETE v1");fflush(stdout);return 0;
}
