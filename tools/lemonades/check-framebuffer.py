#!/usr/bin/env python3
"""Host fault-injection tests of the patched Mu framebuffer initialization code."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REL = Path('Silicon/Silicium/SiliciumPkg/Drivers/SimpleFbDxe/SimpleFb.c')


def function(source, name):
    start = source.index('\n' + name + ' (') + 1
    start = source.rfind('\n', 0, start - 1) + 1  # return type on preceding line
    opening = source.index('{', start)
    depth = 1; end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    with tempfile.TemporaryDirectory(prefix='lemonades-fb-') as temporary:
        tmp = Path(temporary)
        dest = tmp / REL; dest.parent.mkdir(parents=True)
        dest.write_bytes((ROOT / 'Mu-Silicium' / REL).read_bytes())
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(tmp.parent))
        subprocess.run(['git', 'apply', str(ROOT / 'uefi/lemonades/mu-initialization.patch')], cwd=tmp, env=env, check=True)
        source = dest.read_text()
        body = '\n'.join(function(source, name) for name in ('GetFrameBufferInfos', 'FreeMemoryBuffers'))
        # Mock services and PCDs; the two functions under test are extracted
        # unchanged from the actual patched source compiled into the firmware.
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define OUT
#define EFI_ERROR(s) ((s) != 0)
#define DEBUG(x) ((void)0)
#define EFI_SUCCESS 0
#define EFI_NOT_FOUND 14
#define EFI_UNSUPPORTED 3
#define MAX_UINT64 UINT64_MAX
#define VOID void
typedef uint64_t UINT64;
typedef uint32_t UINT32;
typedef uint64_t EFI_PHYSICAL_ADDRESS;
typedef int EFI_STATUS;
typedef struct { uint64_t Address, Length; } EFI_MEMORY_REGION_DESCRIPTOR;
static uint32_t width=1080, height=2400, depth=32;
#define PcdFrameBufferWidth width
#define PcdFrameBufferHeight height
#define PcdFrameBufferColorDepth depth
#define FixedPcdGet32(x) (x)
static int lookup_mode, lookups, frees;
static uint64_t region_address=0x9c000000, region_size=0x2300000;
static int LocateMemoryRegionByName(const char *name, EFI_MEMORY_REGION_DESCRIPTOR *out) {
  lookups++;
  if (lookup_mode == 2 || (lookup_mode == 1 && strcmp(name,"Display Reserved")==0)) return EFI_NOT_FOUND;
  out->Address=region_address; out->Length=region_size; return 0;
}
typedef struct { void *Info; } MODE;
static struct { MODE *Mode; } mFrameBuffer;
static void *FrameBufferConfiguration;
static void FreePool(void *pointer) { assert(pointer); frees++; free(pointer); }
static struct { void (*FreePool)(void *); } services={FreePool}, *gBS=&services;
'''
        checks = r'''
int main(void) {
  uint64_t base=123; uint32_t w,h,d;
  assert(GetFrameBufferInfos(&base,&w,&h,&d)==0 && base==region_address && lookups==1);
  lookup_mode=1; lookups=0;
  assert(GetFrameBufferInfos(&base,&w,&h,&d)==0 && lookups==2);
  lookup_mode=2; base=123;
  assert(GetFrameBufferInfos(&base,&w,&h,&d)==EFI_NOT_FOUND && base==123);
  lookup_mode=0; region_size=4096;
  assert(GetFrameBufferInfos(&base,&w,&h,&d)==EFI_UNSUPPORTED);
  region_size=0x2300000; region_address=UINT64_MAX-1;
  assert(GetFrameBufferInfos(&base,&w,&h,&d)==EFI_UNSUPPORTED);
  region_address=0x9c000000; depth=0;
  assert(GetFrameBufferInfos(&base,&w,&h,&d)==EFI_UNSUPPORTED);
  depth=32; width=height=UINT32_MAX;
  assert(GetFrameBufferInfos(&base,&w,&h,&d)==EFI_UNSUPPORTED);
  FreeMemoryBuffers(); assert(frees==0); /* first allocation failed */
  mFrameBuffer.Mode=calloc(1,sizeof(MODE));
  FreeMemoryBuffers(); assert(frees==1 && mFrameBuffer.Mode==NULL); /* second failed */
  mFrameBuffer.Mode=calloc(1,sizeof(MODE)); mFrameBuffer.Mode->Info=malloc(1);
  FrameBufferConfiguration=malloc(1);
  FreeMemoryBuffers(); assert(frees==4 && mFrameBuffer.Mode==NULL && FrameBufferConfiguration==NULL);
  FreeMemoryBuffers(); assert(frees==4);
  return 0;
}
'''
        test = tmp / 'test.c'; test.write_text(harness + body + checks)
        exe = tmp / 'test'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        str(test), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('Framebuffer lookup, bounds and allocation-failure cleanup passed ASan/UBSan')


if __name__ == '__main__': main()
