#!/usr/bin/env python3
"""ASan/UBSan tests and differential checks against isolated stock Shim code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
from shim_oracle import StockShim, stock_image, ERROR, ROOT, STOCK

BASE = Path('Silicon/Qualcomm/QcomPkg/Library/PlatformPeiLib')
HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <inttypes.h>
#define IN
#define OUT
#define STATIC static
#define VOID void
#define EFI_SUCCESS 0
#define EFI_INVALID_PARAMETER (UINT64_C(0x8000000000000000)|2)
#define EFI_NOT_READY (UINT64_C(0x8000000000000000)|6)
#define EFI_OUT_OF_RESOURCES (UINT64_C(0x8000000000000000)|9)
#define EFI_NOT_FOUND (UINT64_C(0x8000000000000000)|14)
#define EFI_NO_MAPPING (UINT64_C(0x8000000000000000)|17)
#define EFI_ERROR(s) (((s)>>63)!=0)
#define AsciiStriCmp strcasecmp
typedef uintptr_t UINTN;
typedef uint32_t UINT32;
typedef uint64_t EFI_STATUS;
typedef char CHAR8;
static UINT32 InterlockedCompareExchange32(volatile UINT32 *p, UINT32 compare, UINT32 exchange) {
  __atomic_compare_exchange_n(p,&compare,exchange,0,__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST);
  return compare;
}
static int ConfigLib, SioLib, copy_fail;
static EFI_STATUS AsciiStrCpyS(char *dst, size_t cap, const char *src) {
  if(copy_fail) return EFI_INVALID_PARAMETER;
  assert(strlen(src)<cap); memcpy(dst,src,strlen(src)+1); return 0;
}
'''
CHECKS = r'''
static void reset(void) { mShimLibraryCount=2; mShimNamesUsed=0; memset(mShimNames,0,sizeof(mShimNames)); }
static void check(void) {
  void *out=&ConfigLib;
  assert(ShimInstallLib(NULL,1,&SioLib)==EFI_INVALID_PARAMETER);
  assert(ShimInstallLib("",1,&SioLib)==EFI_INVALID_PARAMETER);
  assert(ShimInstallLib("Valid",1,NULL)==EFI_INVALID_PARAMETER);
  assert(mShimLibraryCount==2 && mShimNamesUsed==0);
  assert(ShimLoadLib(NULL,0,&out)==EFI_INVALID_PARAMETER && out==NULL);
  assert(ShimLoadLib("Valid",0,NULL)==EFI_INVALID_PARAMETER);
  assert(ShimLoadLib("absent",0,&out)==EFI_NOT_FOUND && out==NULL);
  assert(ShimLoadLib("SerialPort Lib",0,&out)==0 && out==&SioLib);
  assert(ShimLoadLib("UEFI Config Lib",0x10001,&out)==EFI_NO_MAPPING && out==&ConfigLib);
  mShimRegistryBusy=1;
  assert(ShimLoadLib("SerialPort Lib",0,&out)==EFI_NOT_READY && out==NULL);
  assert(ShimInstallLib("nested",1,&SioLib)==EFI_NOT_READY);
  assert(mShimLibraryCount==2 && mShimNamesUsed==0 && mShimRegistryBusy==1);
  mShimRegistryBusy=0;
  copy_fail=1; assert(ShimInstallLib("failure",1,&SioLib)==EFI_INVALID_PARAMETER);
  assert(mShimLibraryCount==2 && mShimNamesUsed==0); copy_fail=0;
  assert(mShimRegistryBusy==0);
  char name[]="AAAA";
  assert(ShimInstallLib(name,1,&SioLib)==0); name[0]='Z';
  assert(ShimInstallLib("BBBBB",1,&ConfigLib)==0);
  assert(ShimLoadLib("AAAA",1,&out)==0 && out==&SioLib); /* copy and NUL ownership */
  reset();
  char long_name[1025]; memset(long_name,'a',1024); long_name[1024]=0;
  assert(ShimInstallLib(long_name,1,&SioLib)==EFI_OUT_OF_RESOURCES);
  assert(mShimLibraryCount==2 && mShimNamesUsed==0);
  long_name[1023]=0; assert(ShimInstallLib(long_name,1,&SioLib)==0);
  assert(mShimNamesUsed==1024 && mShimLibraryCount==3);
  assert(ShimInstallLib("more",1,&SioLib)==EFI_OUT_OF_RESOURCES);
  assert(ShimLoadLib(long_name,1,&out)==0 && out==&SioLib);
  reset();
  for(unsigned i=0;i<30;i++) { char n[16]; snprintf(n,sizeof(n),"Entry%02u",i); assert(ShimInstallLib(n,i+1,&SioLib)==0); }
  size_t used=mShimNamesUsed;
  assert(ShimInstallLib("overflow",1,&SioLib)==EFI_OUT_OF_RESOURCES);
  assert(mShimLibraryCount==32 && mShimNamesUsed==used);
  assert(ShimLoadLib("Entry29",30,&out)==0 && out==&SioLib);
}
int main(int argc, char **argv) {
  (void)argv;
  if(argc>1) { check(); return 0; }
  char line[4096], name[2048], op; unsigned version; uint64_t pointer;
  while(fgets(line,sizeof(line),stdin)) {
    assert(sscanf(line,"%c %x %" SCNx64 " %2047[^\n]", &op,&version,&pointer,name)==4);
    void *out=NULL; EFI_STATUS status;
    if(op=='I') status=ShimInstallLib(name,version,(void*)(uintptr_t)pointer);
    else { assert(op=='L'); status=ShimLoadLib(name,version,&out); }
    uint64_t value=out==&ConfigLib?0x22000000:out==&SioLib?0x22001000:(uintptr_t)out;
    printf("%016" PRIx64 " %016" PRIx64 "\n",status,value);
  }
  return 0;
}
'''


def cases():
    # All differential names avoid the independently observed stock alignment
    # bug; production boundary tests above intentionally fix that defect.
    result = [[('L','UEFI Config Lib',v,0) for v in (0,0x10001,0x10002,0x10003,0x20001)]]
    result.append([('I','Example Lib',0x10003,0x22100000),('I','example lib',0x10002,0x22101000),
                   ('I','Example Lib',0x10003,0x22102000)] +
                  [('L','EXAMPLE LIB',v,0) for v in (0,0x10001,0x10002,0x10003,0x10004,0x20001)] +
                  [('L','missing',1,0)])
    for seed in range(8):
        rng=random.Random(seed); ops=[]
        for i in range(35):
            # 7-byte strings reserve eight bytes in both implementations.
            name=f'Lib {rng.randrange(6):03d}'
            version=rng.choice([0,1,2,0x10001,0x10002,0x10005,0x20001,0xffff0001])
            ops.append(('I',name,version,0x22100000+i*0x1000))
            for _ in range(3):
                ops.append(('L',f'lib {rng.randrange(8):03d}',rng.choice([0,1,2,3,0x10001,0x10002,0x10003,0x20001,0xffff0001]),0))
        result.append(ops)
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stock',type=Path,default=STOCK)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args(); report={'scope':'Synthetic RAM function emulation, not firmware boot or hardware validation','variants':{}}
    with tempfile.TemporaryDirectory(prefix='lemonades-shim-') as temporary:
        tmp=Path(temporary)
        # Apply the actual build patches, including all files touched by them.
        for patch in ('mu-hob.patch','mu-shim.patch'):
            for line in (ROOT/'uefi/lemonades'/patch).read_text().splitlines():
                if line.startswith('--- a/'):
                    rel=Path(line[6:]); dest=tmp/rel
                    if not dest.exists():
                        dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes((ROOT/'Mu-Silicium'/rel).read_bytes())
            subprocess.run(['git','apply',str(ROOT/'uefi/lemonades'/patch)],cwd=tmp,
                           env=dict(os.environ,GIT_CEILING_DIRECTORIES=str(tmp.parent)),check=True)
        source=(tmp/BASE/'ShimLoader.c').read_text()
        actual=source[source.index('// Shim registration'):]
        c=tmp/'shim.c'; c.write_text(HARNESS+actual+CHECKS); exe=tmp/'shim'
        subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe),'self-test'],check=True)
        for variant in ('xbl','xbl_lp5'):
            data,mapped=stock_image(variant,args.stock); count=0
            for scenario,operations in enumerate(cases()):
                stock=StockShim(mapped)
                assert stock.install('UEFI Config Lib',0x10002,0x22000000)==0
                assert stock.install('SerialPort Lib',0x10001,0x22001000)==0
                stdin=''.join(f'{op} {version:x} {ptr:x} {name}\n' for op,name,version,ptr in operations)
                completed=subprocess.run([str(exe)],input=stdin,text=True,capture_output=True,check=True)
                actual=[tuple(int(x,16) for x in line.split()) for line in completed.stdout.splitlines()]
                expected=[(stock.install(name,version,ptr),0) if op=='I' else stock.load(name,version)
                          for op,name,version,ptr in operations]
                if actual!=expected:
                    mismatch=next(i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b) if len(actual)==len(expected) else -1
                    raise AssertionError(f'{variant} scenario {scenario} mismatch at {mismatch}: {actual[mismatch]} != {expected[mismatch]}')
                count+=len(operations)
            # Confirm the stock defect independently; the C boundary test
            # confirms our replacement keeps the first name intact.
            stock=StockShim(mapped)
            assert stock.install('AAAA',1,0x22100000)==0 and stock.install('BBBBB',1,0x22101000)==0
            assert stock.load('AAAA',1)==(ERROR|14,0)
            report['variants'][variant]={'sec_sha256':hashlib.sha256(data).hexdigest(),
                'matching_operations':count,'scenarios':len(cases()),'stock_aligned_name_overwrite_reproduced':True}
        report['patched_shim_source_sha256']=hashlib.sha256(source.encode()).hexdigest()
        report['patch_sha256']=hashlib.sha256((ROOT/'uefi/lemonades/mu-shim.patch').read_bytes()).hexdigest()
        report['sanitizers']='address,undefined; boundary and differential scenarios passed'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
