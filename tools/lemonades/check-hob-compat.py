#!/usr/bin/env python3
"""Compile actual patched Mu functions with host services and fault injection."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('Silicon/Qualcomm/QcomPkg/Library/PlatformPeiLib')
spec = importlib.util.spec_from_file_location('fb_check', Path(__file__).with_name('check-framebuffer.py'))
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


def main():
    with tempfile.TemporaryDirectory(prefix='lemonades-hob-') as temporary:
        tmp = Path(temporary)
        for name in ('PlatformPei.c', 'Include/FvList.h', 'UefiConfig.c', 'ShimLoader.c'):
            dest = tmp / BASE / name; dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / 'Mu-Silicium' / BASE / name).read_bytes())
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(tmp.parent))
        subprocess.run(['git', 'apply', str(ROOT / 'uefi/lemonades/mu-hob.patch')], cwd=tmp, env=env, check=True)
        body = '\n'.join(helper.function((tmp / BASE / filename).read_text(), name) for filename, name in
                         [('PlatformPei.c', 'CreateFvList'), ('UefiConfig.c', 'LocateConfigurationEntryString'),
                          ('ShimLoader.c', 'ShimLoadLib')])
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#define IN
#define OUT
#define VOID void
#define EFI_SUCCESS 0
#define EFI_INVALID_PARAMETER 2
#define EFI_NOT_READY 6
#define EFI_BUFFER_TOO_SMALL 5
#define EFI_NOT_FOUND 14
#define EFI_ERROR(s) ((s)!=0)
#define DEBUG(x) ((void)0)
#define STATIC_ASSERT _Static_assert
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define EFI_KERNEL_PROTOCOL_VER_LOCK_API 0x10005
#define AsciiSPrint snprintf
#define AsciiStriCmp strcasecmp
#define AsciiStrCmp strcmp
#define AsciiStrSize(s) (strlen(s)+1)
typedef uintptr_t UINTN;
typedef uint64_t UINT64;
typedef uint32_t UINT32;
typedef uint8_t UINT8;
typedef char CHAR8;
typedef int EFI_STATUS;
static char *platform="Windows";
#define PcdPlatformType platform
#define FixedPcdGetPtr(x) (x)
static int copy_status;
static int AsciiStrCpyS(char *out, size_t n, const char *in) {
  if(copy_status) return copy_status;
  assert(n>=strlen(in)+1); memcpy(out,in,strlen(in)+1); return 0;
}
typedef struct { int index; } LockHandle;
typedef struct { int (*InitLock)(const char*, LockHandle**); void (*DestroyLock)(LockHandle*); } LockIntf;
typedef struct { uint64_t Version; LockIntf *Lock; } EFI_KERNEL_PROTOCOL;
static int allocation_fail, allocations, releases, attempts, destroys, fail_at=-1, null_at=-1;
static void *AllocateZeroPool(size_t n) { if(allocation_fail) return NULL; allocations++; return calloc(1,n); }
static void FreePool(void *p) { releases++; free(p); }
static int Init(const char *name, LockHandle **out) {
  int i=attempts++; char expected[16]; snprintf(expected,sizeof(expected),"FVLCK%u",(unsigned)i);
  assert(strcmp(name,expected)==0);
  if(i==fail_at) return 9;
  if(i==null_at) return 0;
  *out=malloc(sizeof(**out)); (*out)->index=i; return 0;
}
static void Destroy(LockHandle *p) { assert(p); destroys++; free(p); }
static int config, serial;
static struct { char *LibName; void *LibIntf; } gShimLibraryInstanceData[]={
 {"UEFI Config Lib",&config}, {"SerialPort Lib",&serial}
};
'''
        checks = r'''
int main(void) {
  LockIntf lock={Init,Destroy}; EFI_KERNEL_PROTOCOL scheduler={0x10005,&lock};
  assert(CreateFvList(NULL)==NULL);
  scheduler.Version=0x10004; assert(CreateFvList(&scheduler)==NULL);
  scheduler.Version=0x20005; assert(CreateFvList(&scheduler)==NULL);
  scheduler.Version=0x10005; scheduler.Lock=NULL; assert(CreateFvList(&scheduler)==NULL);
  scheduler.Lock=&lock; lock.InitLock=NULL; assert(CreateFvList(&scheduler)==NULL);
  lock.InitLock=Init; lock.DestroyLock=NULL; assert(CreateFvList(&scheduler)==NULL);
  lock.DestroyLock=Destroy; assert(allocations==0 && attempts==0);
  allocation_fail=1; assert(CreateFvList(&scheduler)==NULL && attempts==0); allocation_fail=0;
  for(int mode=0;mode<2;mode++) for(int i=0;i<8;i++) {
    attempts=destroys=0; fail_at=mode==0?i:-1; null_at=mode==1?i:-1;
    assert(CreateFvList(&scheduler)==NULL && attempts==i+1 && destroys==i);
    assert(allocations==releases);
  }
  fail_at=null_at=-1; attempts=destroys=0;
  UINTN *list=CreateFvList(&scheduler); assert(list && attempts==8);
  for(unsigned i=0;i<8;i++) {
    // Read the expected byte layout independently of the production macro.
    uint64_t ptr; memcpy(&ptr, (unsigned char*)list+0x18+i*0x48,8);
    LockHandle *handle=(LockHandle*)(uintptr_t)ptr; assert(handle->index==(int)i); Destroy(handle);
  }
  FreePool(list); assert(destroys==8 && allocations==releases);
  char out[16]; memset(out,0x5a,sizeof(out)); size_t capacity=0;
  assert(LocateConfigurationEntryString(NULL,out,&capacity)==EFI_INVALID_PARAMETER);
  assert(LocateConfigurationEntryString("OsTypeString",NULL,&capacity)==EFI_INVALID_PARAMETER);
  assert(LocateConfigurationEntryString("OsTypeString",out,NULL)==EFI_INVALID_PARAMETER);
  for(capacity=0; capacity<8; capacity++) {
    assert(LocateConfigurationEntryString("OsTypeString",out,&capacity)==EFI_BUFFER_TOO_SMALL);
    for(unsigned i=0;i<sizeof(out);i++) assert(out[i]==0x5a);
  }
  assert(LocateConfigurationEntryString("ostypestring",out,&capacity)==0 && capacity==8);
  assert(strcmp(out,"Windows")==0 && out[8]==0x5a);
  copy_status=EFI_INVALID_PARAMETER;
  assert(LocateConfigurationEntryString("OsTypeString",out,&capacity)==EFI_INVALID_PARAMETER);
  copy_status=0; platform=NULL;
  assert(LocateConfigurationEntryString("OsTypeString",out,&capacity)==EFI_NOT_READY);
  platform="NULL"; assert(LocateConfigurationEntryString("OsTypeString",out,&capacity)==EFI_NOT_READY);
  assert(LocateConfigurationEntryString("other",out,&capacity)==EFI_NOT_FOUND);
  void *ptr=&serial;
  assert(ShimLoadLib("absent",0,&ptr)==EFI_NOT_FOUND && ptr==NULL);
  ptr=&serial; assert(ShimLoadLib(NULL,0,&ptr)==EFI_INVALID_PARAMETER && ptr==NULL);
  assert(ShimLoadLib("SerialPort Lib",0,NULL)==EFI_INVALID_PARAMETER);
  assert(ShimLoadLib("SerialPort Lib",0,&ptr)==0 && ptr==&serial);
  assert(ShimLoadLib("uefi config lib",0,&ptr)==0 && ptr==&config);
  return 0;
}
'''
        source = tmp / 'test.c'
        source.write_text(harness + (tmp / BASE / 'Include/FvList.h').read_text() + body + checks)
        exe = tmp / 'test'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                        '-fsanitize=address,undefined', str(source), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('FV byte layout, ABI guards, all 16 lock failures, allocation failure, config bounds and Shim outputs passed ASan/UBSan')


if __name__ == '__main__': main()
