/* Original Libinfo muser wire schema: apple-Libinfo 39b70c515baee5b609e7e91693edbd934b6845a1,
 * lookup.subproj/libinfo_muser.h and muser_module.c. No replacement server. */
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <mach/mach.h>
typedef void *xpc_object_t;
struct xpc_type_s;
typedef const struct xpc_type_s *xpc_type_t;
extern const struct xpc_type_s _xpc_type_dictionary, _xpc_type_bool, _xpc_type_int64, _xpc_type_string, _xpc_type_array;
extern xpc_type_t xpc_get_type(xpc_object_t);
extern xpc_object_t xpc_dictionary_create(const char *const *,const xpc_object_t *,size_t);
extern void xpc_dictionary_set_string(xpc_object_t,const char *,const char *);
extern void xpc_dictionary_set_int64(xpc_object_t,const char *,int64_t);
extern void xpc_dictionary_set_uint64(xpc_object_t,const char *,uint64_t);
extern xpc_object_t xpc_dictionary_get_value(xpc_object_t,const char *);
extern bool xpc_dictionary_get_bool(xpc_object_t,const char *);
extern int64_t xpc_dictionary_get_int64(xpc_object_t,const char *);
extern const char *xpc_dictionary_get_string(xpc_object_t,const char *);
extern size_t xpc_dictionary_get_count(xpc_object_t);
extern size_t xpc_array_get_count(xpc_object_t);
extern kern_return_t host_get_multiuser_config_flags(host_t,uint32_t *);
extern char *xpc_copy_description(xpc_object_t);
extern void xpc_release(xpc_object_t);
/* Private pipe SPI used by the original Libinfo; exported by pinned libSystem. */
extern xpc_object_t xpc_pipe_create(const char *,uint64_t);
extern int xpc_pipe_routine(xpc_object_t,xpc_object_t,xpc_object_t *);
static int typed(xpc_object_t reply,const char *key,xpc_type_t type)
{
    xpc_object_t value=xpc_dictionary_get_value(reply,key);
    return value && xpc_get_type(value)==type;
}
int muser_probe_child(void)
{
    puts("USERMANAGER RPC begin");fflush(stdout);
    uint32_t flags=0;
    if (host_get_multiuser_config_flags(mach_host_self(),&flags)!=KERN_SUCCESS) return 1;
    printf("USERMANAGER RPC multiuser-flags=0x%x\n",flags);
    xpc_object_t pipe=xpc_pipe_create("com.apple.system.libinfo.muser",0);
    if (!pipe) return 1;
    xpc_object_t request=xpc_dictionary_create(NULL,NULL,0),reply=NULL;
    if (!request) {xpc_release(pipe);return 1;}
    xpc_dictionary_set_string(request,"reqtype","available");
    xpc_dictionary_set_int64(request,"version",1);
    int result=xpc_pipe_routine(pipe,request,&reply);xpc_release(request);
    if (result || !reply || xpc_get_type(reply)!=&_xpc_type_dictionary ||
        !typed(reply,"available",&_xpc_type_bool)) {
        printf("USERMANAGER RPC invalid availability result=%d\n",result);
        if (reply) {char *text=xpc_copy_description(reply);if (text) {puts(text);free(text);}xpc_release(reply);}
        xpc_release(pipe);return 1;
    }
    bool available=xpc_dictionary_get_bool(reply,"available");xpc_release(reply);reply=NULL;
    printf("USERMANAGER RPC availability=%d\n",available);fflush(stdout);
    request=xpc_dictionary_create(NULL,NULL,0);
    if (!request) {xpc_release(pipe);return 1;}
    xpc_dictionary_set_string(request,"reqtype","uid");
    xpc_dictionary_set_string(request,"procname","getpwuid");
    xpc_dictionary_set_uint64(request,"version",1);
    xpc_dictionary_set_int64(request,"query",501);
    result=xpc_pipe_routine(pipe,request,&reply);xpc_release(request);
    if (result || !reply || xpc_get_type(reply)!=&_xpc_type_dictionary) {
        printf("USERMANAGER RPC invalid user reply result=%d\n",result);
        if (reply) xpc_release(reply);xpc_release(pipe);return 1;
    }
    char *text=xpc_copy_description(reply);if (text) {puts(text);free(text);}
    int valid=typed(reply,"pw_uid",&_xpc_type_int64) && xpc_dictionary_get_int64(reply,"pw_uid")==501 &&
        typed(reply,"pw_gid",&_xpc_type_int64) && xpc_dictionary_get_int64(reply,"pw_gid")==501 &&
        typed(reply,"pw_name",&_xpc_type_string) && !strcmp(xpc_dictionary_get_string(reply,"pw_name"),"mobile") &&
        typed(reply,"pw_dir",&_xpc_type_string) && !strcmp(xpc_dictionary_get_string(reply,"pw_dir"),"/var/mobile");
    /* Original 0x10002de3c..0x10002df94 consults the multiuser commpage.
     * A single-user boot can return no muser account; Libinfo then uses files.
     * Do not turn on multiuser mode to manufacture a successful mobile reply. */
    bool single_user=(flags&0xc0000000)==0;
    if (single_user && xpc_dictionary_get_count(reply)==0) {
        puts("USERMANAGER RPC mobile not provided in single-user mode");valid=1;
    } else if (valid) puts("USERMANAGER RPC valid mobile reply");
    xpc_release(reply);reply=NULL;
    if (!valid) {xpc_release(pipe);return 1;}
    request=xpc_dictionary_create(NULL,NULL,0);
    if (!request) {xpc_release(pipe);return 1;}
    xpc_dictionary_set_string(request,"reqtype","gid");
    xpc_dictionary_set_string(request,"procname","getgrgid");
    xpc_dictionary_set_uint64(request,"version",1);
    xpc_dictionary_set_int64(request,"query",299);
    result=xpc_pipe_routine(pipe,request,&reply);xpc_release(request);xpc_release(pipe);
    if (result || !reply || xpc_get_type(reply)!=&_xpc_type_dictionary) {
        if (reply) xpc_release(reply);return 1;
    }
    valid=typed(reply,"gr_gid",&_xpc_type_int64) && xpc_dictionary_get_int64(reply,"gr_gid")==299 &&
        typed(reply,"gr_name",&_xpc_type_string) && !strcmp(xpc_dictionary_get_string(reply,"gr_name"),"systemusers") &&
        typed(reply,"gr_members",&_xpc_type_array) && xpc_array_get_count(xpc_dictionary_get_value(reply,"gr_members"))>0;
    xpc_release(reply);
    if (!valid) return 1;
    puts("USERMANAGER RPC valid systemusers reply");fflush(stdout);return 0;
}
