/* Runs against the guest's RAMFS, not the host filesystem. */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/attr.h>
#include <sys/wait.h>

#define REQUIRE(expr) do { if (!(expr)) { \
    printf("BOOTSTRAP FAIL: ramfs line=%d errno=%d\n",__LINE__,errno);return 1; \
} } while (0)
static int put_file(const char *name,char value)
{
    int fd=open(name,O_RDWR|O_CREAT|O_EXCL,0600);
    if (fd<0) return -1;
    if (write(fd,&value,1)!=1) {close(fd);return -1;}
    return fd;
}
static int has_byte(const char *name,char expected)
{
    int fd=open(name,O_RDONLY);char c=0;
    if (fd<0) return 0;
    int ok=read(fd,&c,1)==1 && c==expected;
    close(fd);return ok;
}
static int same_inode(const char *a,const char *b)
{
    struct stat x,y;
    return !stat(a,&x) && !stat(b,&y) && x.st_ino==y.st_ino && x.st_dev==y.st_dev;
}
int check_ramfs_rename(void)
{
    char path[]="/private/var/tmp/rename.XXXXXX",c=0;
    int cwd=open("/",O_RDONLY);REQUIRE(cwd>=0);
    REQUIRE(mkdtemp(path) && !chdir(path));
    struct attrlist request={.bitmapcount=ATTR_BIT_MAP_COUNT,.volattr=ATTR_VOL_INFO|ATTR_VOL_CAPABILITIES};
    struct {uint32_t length;vol_capabilities_attr_t caps;} reply={0};
    REQUIRE(!getattrlist(".",&request,&reply,sizeof(reply),0) && reply.length==sizeof(reply));
    uint32_t rename_caps=VOL_CAP_INT_RENAME_SWAP|VOL_CAP_INT_RENAME_EXCL;
    REQUIRE((reply.caps.valid[VOL_CAPABILITIES_INTERFACES]&rename_caps)==rename_caps &&
            (reply.caps.capabilities[VOL_CAPABILITIES_INTERFACES]&rename_caps)==rename_caps);
    int a=put_file("a",'A'),b=put_file("b",'B');REQUIRE(a>=0 && b>=0);
    struct stat ast,bst,now;
    REQUIRE(!fstat(a,&ast) && !fstat(b,&bst));
    REQUIRE(!renamex_np("a","b",RENAME_SWAP));
    REQUIRE(has_byte("a",'B') && has_byte("b",'A'));
    REQUIRE(!stat("a",&now) && now.st_ino==bst.st_ino && now.st_nlink==1);
    REQUIRE(!stat("b",&now) && now.st_ino==ast.st_ino && now.st_nlink==1);
    REQUIRE(pread(a,&c,1,0)==1 && c=='A');
    REQUIRE(pread(b,&c,1,0)==1 && c=='B');
    REQUIRE(renamex_np("a","missing",RENAME_SWAP)==-1 && errno==ENOENT);
    REQUIRE(renamex_np("a","b",RENAME_EXCL)==-1 && errno==EEXIST);
    REQUIRE(renamex_np("a","b",RENAME_EXCL|RENAME_SWAP)==-1 && errno==EINVAL);
    REQUIRE(has_byte("a",'B') && has_byte("b",'A'));
    REQUIRE(!renamex_np("a","new",RENAME_EXCL) && has_byte("new",'B'));
    REQUIRE(!rename("new","a"));
    REQUIRE(!link("a","alias") && !renamex_np("a","alias",RENAME_SWAP));
    REQUIRE(same_inode("a","alias") && !stat("a",&now) && now.st_nlink==2);
    REQUIRE(!unlink("alias"));
    REQUIRE(!symlink("b","sym") && !renamex_np("sym","a",RENAME_SWAP));
    char target[8]={0};REQUIRE(readlink("a",target,sizeof(target))==1 && target[0]=='b');
    REQUIRE(has_byte("sym",'B') && !renamex_np("sym","a",RENAME_SWAP));
    REQUIRE(!unlink("sym"));
    REQUIRE(!mkdir("p",0700) && !mkdir("q",0700));
    REQUIRE(!mkdir("p/d",0700) && !mkdir("q/e",0700));
    int d=put_file("p/d/item",'D'),e=put_file("q/e/item",'E');REQUIRE(d>=0 && e>=0);
    close(d);close(e);
    REQUIRE(!renamex_np("p/d","q/e",RENAME_SWAP));
    REQUIRE(has_byte("p/d/item",'E') && has_byte("q/e/item",'D'));
    REQUIRE(same_inode("p/d/..","p") && same_inode("q/e/..","q"));
    REQUIRE(!stat("p",&now) && now.st_nlink==3);
    REQUIRE(!renamex_np("p/d","a",RENAME_SWAP)); /* directory/file */
    REQUIRE(has_byte("p/d",'B') && has_byte("a/item",'E'));
    REQUIRE(same_inode("a/..",".") && !stat("p",&now) && now.st_nlink==2);
    REQUIRE(renamex_np("q","q/e",RENAME_SWAP)==-1 && errno==EINVAL);
    REQUIRE(renamex_np("q/e","q",RENAME_SWAP)==-1 && errno==EINVAL);
    REQUIRE(has_byte("q/e/item",'D') && same_inode("q/e/..","q"));
    REQUIRE(!renamex_np("p/d","a",RENAME_SWAP));
    REQUIRE(!stat("p",&now) && now.st_nlink==3);
    /* Independent reader must never see a missing/partial file during swaps.
     * Reading both names would not be an atomic snapshot and is not asserted. */
    pid_t child=fork();REQUIRE(child>=0);
    if (!child) {
        for (unsigned i=0;i<1000;++i) {
            int fd=open("a",O_RDONLY);char value=0;
            if (fd<0 || read(fd,&value,1)!=1 || (value!='A' && value!='B')) _exit(1);
            close(fd);
        }
        _exit(0);
    }
    for (unsigned i=0;i<200;++i) REQUIRE(!renamex_np("a","b",RENAME_SWAP));
    int status=-1;REQUIRE(waitpid(child,&status,0)==child && status==0);
    REQUIRE(has_byte("a",'B') && has_byte("b",'A'));
    REQUIRE(!rename("a","b") && has_byte("b",'B'));
    REQUIRE(!fstat(a,&now) && now.st_nlink==0 && pread(a,&c,1,0)==1 && c=='A');
    close(a);close(b);
    REQUIRE(!unlink("b") && !unlink("p/d/item") && !unlink("q/e/item"));
    REQUIRE(!rmdir("p/d") && !rmdir("q/e") && !rmdir("p") && !rmdir("q"));
    REQUIRE(!fchdir(cwd));close(cwd);REQUIRE(!rmdir(path));
    puts("RAMFS PASS rename-swap-excl");return 0;
}
