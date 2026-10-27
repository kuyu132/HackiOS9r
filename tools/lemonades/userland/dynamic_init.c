/* Static PID1 for the APFS -> Apple dyld -> libSystem integration test. */
#define start bsd_probe_start
#include "abi_probe.c"
#undef start
enum { DYN_SYS_execve=59, DYN_SYS_dup2=90, DYN_SYS_mount=167, DYN_SYS_mkdir=136, DYN_SYS_chmod=15, DYN_SYS_chown=16 };
void start(void)
{
    struct result opened=CALL(SYS_open,"/dev/console",O_RDWR,0);
    if (opened.error) terminate(1);
    console=(int)opened.value;
    for (int fd=0;fd<3;++fd) checked(CALL(DYN_SYS_dup2,console,fd,0),"console dup2");
    put("DYN INIT v1\n");
    struct result child=CALL(SYS_fork,0,0,0);
    checked(child,"dynamic fork");
    if (child.second) {
        char *argv[]={"/bin/dynamic_probe","from-pid1",0};
        char *env[]={"PATH=/bin:/usr/bin","HOME=/",0};
        CALL(DYN_SYS_execve,argv[0],argv,env);
        fail("dynamic execve returned");
    }
    int status=-1;
    if (child.value<=1 || checked(CALL(SYS_wait4,child.value,&status,0),"dynamic wait")!=child.value ||
        status!=(7<<8)) fail("dynamic child status");
    put("DYN PASS child-exit\n");
    put("DYN COMPLETE v1\n");
#ifdef HANDOFF_APPLE_LAUNCHD
    /* Writable state is isolated in RAM. Original filesystem stays read-only. */
    checked(call(DYN_SYS_mount,(long)"ramfs",(long)"/private/var",0,0,0,0),"mount var ramfs");
    const char *dirs[]={"/private/var/run","/private/var/tmp","/private/var/db",
        "/private/var/db/com.apple.xpc.launchd","/private/var/log","/private/var/logs","/private/var/root"};
    for (unsigned i=0;i<sizeof(dirs)/sizeof(dirs[0]);++i)
        checked(CALL(DYN_SYS_mkdir,dirs[i],0755,0),"mkdir writable state");
    checked(CALL(DYN_SYS_chmod,"/private/var/tmp",01777,0),"tmp permissions");
#ifdef INIT_CORE_SERVICES
    /* diagnostics/mobile modes and owners measured on the original data template.
     * uuidtext/timesync are fresh runtime log directories (reference init.c). */
    struct {const char *path;int mode,uid,gid;} owned[]={
        {"/private/var/mobile",0711,501,501},
        {"/private/var/db/diagnostics",0751,272,272},
        {"/private/var/db/diagnostics/timesync",0755,272,272},
        {"/private/var/db/uuidtext",0755,272,272}};
    for (unsigned i=0;i<sizeof(owned)/sizeof(owned[0]);++i) {
        checked(CALL(DYN_SYS_mkdir,owned[i].path,owned[i].mode,0),"core data mkdir");
        checked(CALL(DYN_SYS_chmod,owned[i].path,owned[i].mode,0),"core data chmod");
        checked(CALL(DYN_SYS_chown,owned[i].path,owned[i].uid,owned[i].gid),"core data chown");
    }
    const char *markers[]={"/private/var/db/diagnostics/.migrated",
        "/private/var/db/diagnostics/timesync/.migrated","/private/var/db/uuidtext/.migrated"};
    for (unsigned i=0;i<sizeof(markers)/sizeof(markers[0]);++i) {
        long fd=checked(CALL(SYS_open,markers[i],0x201,0644),"fresh log marker");
        checked(CALL(DYN_SYS_chown,markers[i],272,272),"log marker owner");close_fd(fd);
    }
    put("CORE DATA ready\n");
#endif
#ifdef INIT_USERMANAGER_BOOT
    /* Empty RAM data volume: the original initializer writes its own manifests.
     * Root-only access is a bring-up policy, not an observed template mode. */
    checked(CALL(DYN_SYS_mkdir,"/private/var/keybags",0700,0),"keybags directory");
    /* launchd's embedded boot-task table uses --init before normal daemon start.
     * Its boot tasks run without XPC services; reproduce that isolated setup. */
    put("USERMANAGER INIT begin\n");
    struct result init_child=CALL(SYS_fork,0,0,0);
    checked(init_child,"usermanager init fork");
    if (init_child.second) {
        char *init_args[]={"/usr/libexec/usermanagerd","--init",0};
        char *init_env[]={"PATH=/usr/bin:/bin:/usr/sbin:/sbin","HOME=/var/root",
            "XPC_SERVICES_UNAVAILABLE=1","XPC_NULL_BOOTSTRAP=1","OS_ACTIVITY_DT_MODE=YES",0};
        CALL(DYN_SYS_execve,init_args[0],init_args,init_env);
        fail("usermanager init exec returned");
    }
    int init_status=-1;
    if (checked(CALL(SYS_wait4,init_child.value,&init_status,0),"usermanager init wait")!=init_child.value || init_status!=0)
        fail("usermanager init exit status");
    put("USERMANAGER PASS boot-task\n");
#endif
#ifdef INIT_PREFERENCES_BOOT
    /* Fresh root diagnostic account state on the RAM volume. These restrictive
     * modes are test policy, not claims about the original data template. */
    checked(CALL(DYN_SYS_mkdir,"/private/var/root/Library",0700,0),"root library");
    checked(CALL(DYN_SYS_mkdir,"/private/var/root/Library/Preferences",0700,0),"root preferences");
#ifndef INIT_CORE_SERVICES
    checked(CALL(DYN_SYS_mkdir,"/private/var/mobile",0711,0),"mobile home");
    checked(CALL(DYN_SYS_chown,"/private/var/mobile",501,501),"mobile home owner");
#endif
    const char *mobile_dirs[]={"/private/var/mobile/Library","/private/var/mobile/Library/Preferences"};
    for(unsigned i=0;i<2;++i){
        checked(CALL(DYN_SYS_mkdir,mobile_dirs[i],0700,0),"mobile preferences directory");
        checked(CALL(DYN_SYS_chown,mobile_dirs[i],501,501),"mobile preferences owner");
    }
#endif
#ifdef INIT_BACKBOARD_BOOT
    /* Diagnostic log destination owned by the original job's mobile user.
     * Keep devfs console permissions intact. */
    checked(CALL(DYN_SYS_mkdir,"/private/var/mobile/Library/Logs",0700,0),"backboard logs");
    checked(CALL(DYN_SYS_chown,"/private/var/mobile/Library/Logs",501,501),"backboard logs owner");
    const char *backboard_log="/private/var/mobile/Library/Logs/backboard-bringup.log";
    long log_fd=checked(CALL(SYS_open,backboard_log,0x201,0600),"backboard log file");
    checked(CALL(DYN_SYS_chown,backboard_log,501,501),"backboard log owner");close_fd(log_fd);
#endif
#ifdef INIT_CONTAINER_BOOT
    /* Measured on the pinned original rootfs data template: _installd 33:33,
     * 0755. Container roots themselves are absent and left for the provider. */
    checked(CALL(DYN_SYS_mkdir,"/private/var/installd",0755,0),"installd home");
    checked(CALL(DYN_SYS_chown,"/private/var/installd",33,33),"installd home owner");
#endif
    char *argv[]={"/sbin/launchd.apple",0};
    char *env[]={"PATH=/bin:/sbin:/usr/bin:/usr/sbin","HOME=/var/root",0};
    put("LAUNCHD HANDOFF v1\n");
    CALL(DYN_SYS_execve,argv[0],argv,env);
    fail("Apple launchd execve returned");
#else
    terminate(0);
#endif
}
