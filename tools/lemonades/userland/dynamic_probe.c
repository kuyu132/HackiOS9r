/* Runs through real iOS dyld and libSystem, not a raw-syscall replacement. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/utsname.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <mach-o/dyld.h>
#ifdef CHECK_SYSTEM_USERS
#include <pwd.h>
#include <grp.h>
#endif
/* Exported by the pinned libSystem; syscall 294 takes uint64_t * in XNU. */
extern int __shared_region_check_np(uint64_t *address);
int main(int argc,char **argv)
{
    struct utsname system;
    if (argc!=2 || strcmp(argv[1],"from-pid1") || getpid()<=1 || getppid()!=1) return 2;
    if (uname(&system)!=0 || strcmp(system.sysname,"Darwin")) return 3;
    if (!_dyld_shared_cache_contains_path("/usr/lib/libSystem.B.dylib") ||
        _dyld_shared_cache_contains_path("/not/a/real/library/hackios9r.dylib")) return 6;
    uint64_t shared_address=0;
    int shared_result=__shared_region_check_np(&shared_address);
    int shared_errno=shared_result==0 ? 0 : errno;
    printf("DYN PASS active-cache shared_result=%d errno=%d address=0x%llx\n",
        shared_result,shared_errno,(unsigned long long)shared_address);
#ifdef CHECK_SYSTEM_USERS
    struct passwd *user=getpwnam("mobile");
    if (!user || user->pw_uid!=501 || user->pw_gid!=501) return 8;
    user=getpwnam("root");
    if (!user || user->pw_uid!=0 || user->pw_gid!=0) return 8;
    struct group *group=getgrnam("mobile");
    if (!group || group->gr_gid!=501) return 8;
    puts("DYN PASS users");
#endif
    volatile unsigned char *memory=malloc(65536);
    if (!memory) return 4;
    for (unsigned i=0;i<65536;++i) memory[i]=(char)(i*13+5);
    for (unsigned i=0;i<65536;++i) if ((unsigned char)memory[i]!=(unsigned char)(i*13+5)) return 5;
    free((void *)memory);
    printf("DYN PASS libSystem pid=%d kernel=%s machine=%s\n",getpid(),system.release,system.machine);
    fflush(stdout);
    return 7;
}
