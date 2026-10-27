/* Exercise original CoreFoundation preferences in separate exec processes.
 * Only this diagnostic app domain is written, on the disposable guest RAM disk. */
#include <CoreFoundation/CoreFoundation.h>
#include <mach/mach.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <spawn.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/event.h>
#include <grp.h>
extern kern_return_t bootstrap_look_up(mach_port_t,const char *,mach_port_t *);
#define APP CFSTR("net.hackios9r.preferences-probe")
#define KEY CFSTR("RoundTripNonce")
static int prefs_fail(const char *stage) {printf("BOOTSTRAP FAIL: preferences %s\n",stage);fflush(stdout);return 1;}

int preferences_probe_child(const char *operation,const char *nonce)
{
    if(!strncmp(operation,"mobile-",7)){
        gid_t group=501;
        if(setgroups(1,&group) || setgid(501) || setuid(501))return prefs_fail("mobile credentials");
        char mode[40];snprintf(mode,sizeof(mode),"user-%s",operation+7);
        char *args[]={"/bin/bootstrap_probe","preferences-child",mode,(char *)nonce,NULL};
        char *env[]={"PATH=/bin:/usr/bin","HOME=/var/mobile","OS_ACTIVITY_DT_MODE=YES",NULL};
        execve(args[0],args,env);return prefs_fail("mobile exec");
    }
    uid_t expected_uid=0;
    if(!strncmp(operation,"user-",5)){expected_uid=501;operation+=5;}
    if(getuid()!=expected_uid || geteuid()!=expected_uid || getgid()!=expected_uid || getegid()!=expected_uid)
        return prefs_fail("preferences caller identity");
    CFStringRef expected=CFStringCreateWithCString(NULL,nonce,kCFStringEncodingUTF8);
    if (!expected) return prefs_fail("allocate value");
    if (!strcmp(operation,"write") || !strcmp(operation,"remove")) {
        CFPreferencesSetValue(KEY,!strcmp(operation,"write") ? expected : NULL,APP,
                              kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
        if (!CFPreferencesSynchronize(APP,kCFPreferencesCurrentUser,kCFPreferencesAnyHost)) {
            CFRelease(expected);return prefs_fail("synchronize write");
        }
    } else if (!strcmp(operation,"read") || !strcmp(operation,"absent") || !strcmp(operation,"diagnose")) {
        if (!CFPreferencesSynchronize(APP,kCFPreferencesCurrentUser,kCFPreferencesAnyHost)) {
            CFRelease(expected);return prefs_fail("synchronize read");
        }
        CFTypeRef value=CFPreferencesCopyValue(KEY,APP,kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
        int valid=!strcmp(operation,"absent") ? value==NULL :
            value && CFGetTypeID(value)==CFStringGetTypeID() && CFEqual(value,expected);
        if (value) CFRelease(value);
        if (!strcmp(operation,"diagnose")) {
            printf("PREFS fresh observation matches-external=%d pid=%d\n",valid,getpid());
            CFRelease(expected);fflush(stdout);return 0;
        }
        if (!valid) {CFRelease(expected);return prefs_fail("fresh-process value");}
    } else {CFRelease(expected);return prefs_fail("unknown operation");}
    CFRelease(expected);printf("PREFS child %s passed pid=%d uid=%d\n",operation,getpid(),getuid());fflush(stdout);return 0;
}

static int saved_failure(int quiet,const char *stage) {return quiet?1:prefs_fail(stage);}
static int saved_value_at(const char *path,uid_t owner,const char *nonce,int quiet)
{
    FILE *f=fopen(path,"rb");
    if (!f) return saved_failure(quiet,"saved file missing");
    struct stat st;
    if (fstat(fileno(f),&st) || !S_ISREG(st.st_mode) || st.st_uid!=owner || (st.st_mode&0022) ||
        st.st_size<=0 || st.st_size>65536) {fclose(f);return saved_failure(quiet,"saved metadata");}
    unsigned char bytes[65536];size_t count=fread(bytes,1,(size_t)st.st_size,f);fclose(f);
    if (count!=(size_t)st.st_size) return saved_failure(quiet,"saved read");
    CFDataRef data=CFDataCreate(NULL,bytes,(CFIndex)count);
    CFPropertyListRef plist=data?CFPropertyListCreateWithData(NULL,data,kCFPropertyListImmutable,NULL,NULL):NULL;
    if(data)CFRelease(data);
    CFStringRef expected=CFStringCreateWithCString(NULL,nonce,kCFStringEncodingUTF8);
    CFTypeRef value=plist && CFGetTypeID(plist)==CFDictionaryGetTypeID()?CFDictionaryGetValue(plist,KEY):NULL;
    int valid=expected && value && CFGetTypeID(value)==CFStringGetTypeID() && CFEqual(value,expected);
    if(expected)CFRelease(expected);if(plist)CFRelease(plist);
    return valid?0:saved_failure(quiet,"saved value");
}

static int saved_value_check(const char *nonce,int quiet) {
    return saved_value_at("/private/var/root/Library/Preferences/net.hackios9r.preferences-probe.plist",0,nonce,quiet);
}
static int saved_value(const char *nonce) {return saved_value_check(nonce,0);}

static int run_pref_child(const char *operation,const char *nonce)
{
    pid_t child=-1;char *args[]={"/bin/bootstrap_probe","preferences-child",(char *)operation,(char *)nonce,NULL};
    char *env[]={"PATH=/bin:/usr/bin","HOME=/var/root","OS_ACTIVITY_DT_MODE=YES",NULL};
    if(posix_spawn(&child,args[0],NULL,NULL,args,env))return prefs_fail("spawn");
    int done=0,status=-1;
    for(unsigned attempt=0;attempt<40;++attempt) {
        pid_t waited=waitpid(child,&status,WNOHANG);
        if(waited==child){done=1;break;}
        if(waited<0 && errno!=EINTR)break;
        usleep(250000);
    }
    if(!done){kill(child,SIGKILL);waitpid(child,&status,0);return prefs_fail("child timeout");}
    return status?prefs_fail("child status"):0;
}

static int matches_cached_value(const char *nonce)
{
    CFStringRef expected=CFStringCreateWithCString(NULL,nonce,kCFStringEncodingUTF8);
    CFTypeRef value=CFPreferencesCopyValue(KEY,APP,kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
    int valid=expected && value && CFGetTypeID(value)==CFStringGetTypeID() && CFEqual(value,expected);
    if(value)CFRelease(value);if(expected)CFRelease(expected);return valid;
}

static int check_mobile_preferences(const char *root_nonce)
{
    char mobile_nonce[100];snprintf(mobile_nonce,sizeof(mobile_nonce),"%s-mobile",root_nonce);
    if(!matches_cached_value(root_nonce))return prefs_fail("root initial isolation value");
    if(run_pref_child("mobile-write",mobile_nonce) || run_pref_child("mobile-read",mobile_nonce))return 1;
    int saved=0;
    for(unsigned i=0;i<80;++i){
        saved=!saved_value_at("/private/var/mobile/Library/Preferences/net.hackios9r.preferences-probe.plist",501,mobile_nonce,1);
        if(saved)break;usleep(100000);
    }
    if(!saved)return prefs_fail("mobile saved file");
    if(!CFPreferencesSynchronize(APP,kCFPreferencesCurrentUser,kCFPreferencesAnyHost) ||
       !matches_cached_value(root_nonce) || saved_value(root_nonce))return prefs_fail("root/mobile isolation");
    if(run_pref_child("mobile-remove",mobile_nonce) || run_pref_child("mobile-absent",mobile_nonce))return 1;
    if(!matches_cached_value(root_nonce))return prefs_fail("mobile deletion changed root");
    puts("PREFS PASS mobile-isolation");fflush(stdout);return 0;
}

#ifdef CHECK_FSEVENTS
static int check_api_refresh(char *nonce,size_t capacity)
{
    if(!matches_cached_value(nonce))return prefs_fail("API initial cache");
    char updated[100];snprintf(updated,sizeof(updated),"%s-api",nonce);
    if(strlen(updated)>=capacity)return prefs_fail("API nonce length");
    if(run_pref_child("write",updated))return 1;
    int observed=0,on_disk=0;
    for(unsigned i=0;i<80;++i){
        observed=CFPreferencesSynchronize(APP,kCFPreferencesCurrentUser,kCFPreferencesAnyHost) && matches_cached_value(updated);
        on_disk=!saved_value_check(updated,1);
        if(observed && on_disk){printf("PREFS API refreshed poll=%u\n",i);break;}
        if(i%10==0){printf("PREFS API pending poll=%u cache=%d saved=%d\n",i,observed,on_disk);fflush(stdout);}
        usleep(100000);
    }
    if(!observed)return prefs_fail("API live cache refresh timeout");
    if(!on_disk)return prefs_fail("API saved value timeout");
    strcpy(nonce,updated);puts("PREFS PASS api-live-refresh");fflush(stdout);return 0;
}
static int check_external_preferences(const char *nonce)
{
    CFStringRef old=CFStringCreateWithCString(NULL,nonce,kCFStringEncodingUTF8);
    CFTypeRef cached=CFPreferencesCopyValue(KEY,APP,kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
    int warm=old && cached && CFGetTypeID(cached)==CFStringGetTypeID() && CFEqual(cached,old);
    if(cached)CFRelease(cached);if(old)CFRelease(old);
    if(!warm)return prefs_fail("external initial cache");
    char updated[100];snprintf(updated,sizeof(updated),"%s-external",nonce);
    CFStringRef value=CFStringCreateWithCString(NULL,updated,kCFStringEncodingUTF8);
    const void *key=KEY;const void *item=value;
    CFDictionaryRef dict=value?CFDictionaryCreate(NULL,&key,&item,1,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks):NULL;
    CFDataRef data=dict?CFPropertyListCreateData(NULL,dict,kCFPropertyListBinaryFormat_v1_0,0,NULL):NULL;
    if(dict)CFRelease(dict);
    if(!data){if(value)CFRelease(value);return prefs_fail("external serialization");}
    /* Observe the original file inode and parent directory independently of
     * Foundation's cache. No events or notifications are fabricated. */
    int oldfd=open("/private/var/root/Library/Preferences/net.hackios9r.preferences-probe.plist",O_EVTONLY);
    int dirfd=open("/private/var/root/Library/Preferences",O_EVTONLY),queue=kqueue();
    struct kevent registrations[2];
    EV_SET(&registrations[0],oldfd,EVFILT_VNODE,EV_ADD|EV_CLEAR,NOTE_DELETE|NOTE_RENAME|NOTE_WRITE,0,NULL);
    EV_SET(&registrations[1],dirfd,EVFILT_VNODE,EV_ADD|EV_CLEAR,NOTE_WRITE,0,NULL);
    if(oldfd<0 || dirfd<0 || queue<0 || kevent(queue,registrations,2,NULL,0,NULL)<0){
        if(oldfd>=0)close(oldfd);if(dirfd>=0)close(dirfd);if(queue>=0)close(queue);
        CFRelease(data);CFRelease(value);return prefs_fail("external vnode watch");
    }
    char temporary[]="/private/var/root/Library/Preferences/net.hackios9r.external-XXXXXX";
    int fd=mkstemp(temporary),written=fd>=0;size_t offset=0,length=(size_t)CFDataGetLength(data);
    while(written && offset<length){
        ssize_t count=write(fd,CFDataGetBytePtr(data)+offset,length-offset);
        if(count<0 && errno==EINTR)continue;
        if(count<=0){written=0;break;}offset+=(size_t)count;
    }
    CFRelease(data);
    if(fd>=0){if(fsync(fd))written=0;if(close(fd))written=0;}
    if(!written || rename(temporary,"/private/var/root/Library/Preferences/net.hackios9r.preferences-probe.plist")){
        unlink(temporary);close(oldfd);close(dirfd);close(queue);CFRelease(value);return prefs_fail("external atomic replace");
    }
    struct kevent events[2];struct timespec timeout={1,0};
    int count=kevent(queue,NULL,0,events,2,&timeout),file_event=0,dir_event=0;
    for(int i=0;i<count;++i){
        printf("PREFS vnode event ident=%llu flags=0x%x fflags=0x%x\n",(unsigned long long)events[i].ident,events[i].flags,events[i].fflags);
        if(!(events[i].flags&EV_ERROR) && events[i].filter==EVFILT_VNODE){
            if(events[i].ident==(uintptr_t)oldfd && (events[i].fflags&NOTE_DELETE))file_event=1;
            if(events[i].ident==(uintptr_t)dirfd && (events[i].fflags&NOTE_WRITE))dir_event=1;
        }
    }
    close(oldfd);close(dirfd);close(queue);
    if(!file_event || !dir_event){CFRelease(value);return prefs_fail("external vnode notification");}
    puts("PREFS PASS external-vnode-events");fflush(stdout);
    if(saved_value(updated)){CFRelease(value);return 1;}
    /* Keep this process alive with its old cached value. Synchronize is the
     * public refresh API; no private cache reset or synthetic notify is used. */
    int observed=0;
    for(unsigned i=0;i<400;++i){
        Boolean synced=CFPreferencesSynchronize(APP,kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
        CFTypeRef current=CFPreferencesCopyValue(KEY,APP,kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
        observed=synced && current && CFGetTypeID(current)==CFStringGetTypeID() && CFEqual(current,value);
        if(current)CFRelease(current);
        if(observed){printf("PREFS external refreshed poll=%u\n",i);break;}
        if(i%50==0){printf("PREFS external pending poll=%u synchronized=%d\n",i,synced);fflush(stdout);}
        usleep(100000);
    }
    CFRelease(value);
    if(!observed){
        if(!saved_value(updated)){puts("PREFS external file still matches replacement");fflush(stdout);}
        run_pref_child("diagnose",updated);
        return prefs_fail("external cache refresh timeout");
    }
    if(saved_value(updated))return 1;
    puts("PREFS PASS external-refresh");fflush(stdout);return 0;
}
#endif

int check_preferences(void)
{
    mach_port_t port=MACH_PORT_NULL;
    if (bootstrap_look_up(bootstrap_port,"com.apple.cfprefsd.daemon",&port)!=KERN_SUCCESS || !MACH_PORT_VALID(port))
        return prefs_fail("daemon lookup");
    mach_port_deallocate(mach_task_self(),port);
    struct timeval now;gettimeofday(&now,NULL);char nonce[80];
    snprintf(nonce,sizeof(nonce),"%d-%lld-%d",getpid(),(long long)now.tv_sec,(int)now.tv_usec);
    const char *operations[]={"write","read","remove","absent"};
    for (unsigned i=0;i<4;++i) {
        if(run_pref_child(operations[i],nonce))return 1;
        if(i==0 && saved_value(nonce))return 1;
        if(i==1 && check_mobile_preferences(nonce))return 1;
#ifdef CHECK_FSEVENTS
        if(i==1 && (check_api_refresh(nonce,sizeof(nonce)) || check_external_preferences(nonce)))return 1;
#endif
    }
    puts("PREFS PASS cross-process");fflush(stdout);return 0;
}
