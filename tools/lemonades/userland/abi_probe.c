/* Standalone static ARM64 Darwin user-space probe. No libc, dyld or Apple
 * system-image files. Constants/return ABI match xnu-8796.121.2 syscalls.master,
 * sys/mman.h, kern_fork.c and sys_pipe.c. Runs as PID 1 on the mockfs ramdisk.
 * This checks kernel primitives, not launchd or full iOS compatibility. */
typedef unsigned long u64;
struct result { long value, second; unsigned long error; };
enum { SYS_exit=1, SYS_fork=2, SYS_read=3, SYS_write=4, SYS_open=5,
    SYS_close=6, SYS_wait4=7, SYS_getpid=20, SYS_getuid=24,
    SYS_getppid=39, SYS_pipe=42, SYS_munmap=73, SYS_mprotect=74, SYS_mmap=197 };
enum { O_RDWR=2, PROT_READ=1, PROT_WRITE=2, MAP_PRIVATE=2, MAP_ANON=0x1000, EBADF=9 };

static struct result call(long number, long a, long b, long c, long d, long e, long f)
{
    register long x16 __asm__("x16")=number;
    register long x0 __asm__("x0")=a, x1 __asm__("x1")=b;
    register long x2 __asm__("x2")=c, x3 __asm__("x3")=d;
    register long x4 __asm__("x4")=e, x5 __asm__("x5")=f;
    unsigned long error;
    __asm__ volatile("svc #0x80\n\tcset %2, cs"
        : "+r"(x0), "+r"(x1), "=&r"(error)
        : "r"(x16), "r"(x2), "r"(x3), "r"(x4), "r"(x5) : "memory", "cc");
    return (struct result){x0,x1,error};
}
#define CALL(n,a,b,c) call(n,(long)(a),(long)(b),(long)(c),0,0,0)
static int console;
static void put(const char *text)
{
    u64 length=0;
    while (text[length]) ++length;
    while (length) {
        struct result r=CALL(SYS_write,console,text,length);
        if (r.error || r.value<=0 || (u64)r.value>length) break;
        text+=r.value; length-=r.value;
    }
}
__attribute__((noreturn)) static void terminate(int status)
{
    CALL(SYS_exit,status,0,0);
    for (;;) {}
}
__attribute__((noreturn)) static void fail(const char *stage)
{
    put("ABI FAIL: "); put(stage); put("\n"); terminate(1);
}
static long checked(struct result r, const char *stage)
{
    if (r.error) fail(stage);
    return r.value;
}
static void close_fd(long fd)
{
    if (checked(CALL(SYS_close,fd,0,0),"close")!=0) fail("close return");
}
void start(void)
{
    struct result opened=CALL(SYS_open,"/dev/console",O_RDWR,0);
    if (opened.error) terminate(1);
    console=(int)opened.value;
    put("ABI BEGIN v1\n");
    if (checked(CALL(SYS_getpid,0,0,0),"getpid")!=1 ||
        checked(CALL(SYS_getuid,0,0,0),"getuid")!=0) fail("PID1 identity");
    put("ABI PASS identity\n");
    unsigned char token=0;
    struct result bad=CALL(SYS_read,-1,&token,1);
    if (!bad.error || bad.value!=EBADF) fail("carry/errno");
    put("ABI PASS errno\n");
    enum { BYTES=65536 };
    struct result mapping=call(SYS_mmap,0,BYTES,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
    volatile unsigned char *memory=(void *)checked(mapping,"mmap");
    if (!memory) fail("null mapping");
    for (u64 i=0;i<BYTES;++i) {
        if (memory[i]!=0) fail("anonymous zero fill");
        memory[i]=(unsigned char)(i*17+3);
    }
    if (checked(CALL(SYS_mprotect,memory,BYTES,PROT_READ),"mprotect read")!=0) fail("mprotect read result");
    for (u64 i=0;i<BYTES;++i)
        if (memory[i]!=(unsigned char)(i*17+3)) fail("mapped readback");
    if (checked(CALL(SYS_mprotect,memory,BYTES,PROT_READ|PROT_WRITE),"mprotect write")!=0)
        fail("mprotect write result");
    put("ABI PASS vm\n");
    struct result pipe=CALL(SYS_pipe,0,0,0);
    checked(pipe,"pipe");
    if (pipe.value<0 || pipe.second<0 || pipe.value==pipe.second) fail("pipe descriptors");
    struct result forked=CALL(SYS_fork,0,0,0);
    checked(forked,"fork");
    if (forked.second) {
        if (checked(CALL(SYS_getpid,0,0,0),"child pid")<=1 ||
            checked(CALL(SYS_getppid,0,0,0),"child parent")!=1) fail("child identity");
        close_fd(pipe.value);
        for (u64 i=0;i<BYTES;i+=4096) memory[i]^=0xff;
        token=0x5a;
        if (checked(CALL(SYS_write,pipe.second,&token,1),"child pipe write")!=1) fail("short pipe write");
        close_fd(pipe.second);
        terminate(37);
    }
    if (forked.value<=1) fail("parent fork result");
    close_fd(pipe.second);
    if (checked(CALL(SYS_read,pipe.value,&token,1),"parent pipe read")!=1 || token!=0x5a)
        fail("pipe transfer");
    if (checked(CALL(SYS_read,pipe.value,&token,1),"pipe EOF")!=0) fail("pipe EOF result");
    close_fd(pipe.value);
    int status=-1;
    if (checked(CALL(SYS_wait4,forked.value,&status,0),"wait4")!=forked.value || status!=(37<<8))
        fail("wait/child exit");
    put("ABI PASS process-ipc\n");
    for (u64 i=0;i<BYTES;++i)
        if (memory[i]!=(unsigned char)(i*17+3)) fail("copy-on-write isolation");
    if (checked(CALL(SYS_munmap,memory,BYTES,0),"munmap")!=0) fail("munmap result");
    put("ABI PASS cow-cleanup\n");
    put("ABI COMPLETE v1\n");
    /* Mockfs has no service manager. Only this exit-0 PID1 panic is expected. */
    terminate(0);
}
