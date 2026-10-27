#!/usr/bin/env python3
"""Export isolated, pinned Mu sources and a staged 9R overlay for offline builds."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
REPOS = {
    '': '4cba43c90e02cdbefbcd9fcdbda33d2328deaec0',
    'Mu_Basecore': '3c9c7b2e211e62d2a954ad760a36fe05adc43aa3',
    'Common/Mu': 'b8d46c71610318e36a661819e1e3c0b8bdda413a',
    'Common/Mu_OEM_Sample': 'b70b4b7bb02c43bf9db2172dfb3ed0457e2361d6',
    'Silicium-ACPI': '1c8bd63a7ffcaecf3c8764a6b01a11e053457543',
    'Silicon/Silicium/OpensslPkg/Library/OpensslLib/openssl': '67b5686b4419b4cb8caa502711c41815f5279751',
    'Mu_Basecore/BaseTools/Source/C/BrotliCompress/brotli': 'e230f474b87134e8c6c85b630084c612057f253e',
    'Mu_Basecore/MdeModulePkg/Library/BrotliCustomDecompressLib/brotli': 'e230f474b87134e8c6c85b630084c612057f253e',
    'Mu_Basecore/MdePkg/Library/BaseFdtLib/libfdt': 'cfff805481bdea27f900c32698171286542b8d3c',
    'Mu_Basecore/MdePkg/Library/MipiSysTLib/mipisyst': '370b5944c046bab043dd8b133727b2135af7747a',
    'Mu_Basecore/SecurityPkg/DeviceSecurity/SpdmLib/libspdm': 'f55cf6d48ec69b4ac60a63903e9c6a2cb0fd155d',
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--overlay', type=Path, default=ROOT / 'out/lemonades/uefi-stock-overlay')
    ap.add_argument('--output', type=Path, default=ROOT / 'out/lemonades/mu-build')
    args = ap.parse_args()
    out = args.output.resolve()
    if out.exists(): ap.error('output exists; use a fresh build directory')
    for relative, revision in REPOS.items():
        repo = ROOT / 'Mu-Silicium' / relative
        subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', revision + '^{commit}'], check=True)
    out.mkdir(parents=True)
    for relative, revision in REPOS.items():
        print('Export ' + (relative or 'Mu-Silicium'), flush=True)
        data = subprocess.check_output(['git', '-C', str(ROOT / 'Mu-Silicium' / relative), 'archive', revision])
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(out / relative, filter='data')
    shutil.copytree(args.overlay, out, dirs_exist_ok=True)
    patches = ['AsmMacroLib.patch', 'Auth-Service.patch', 'Boot-Manager.patch', 'Timer.patch', 'Usb-Bus.patch']
    for patch in patches:
        # Exports have no .git. Prevent git from discovering the enclosing HackiOS
        # repository and silently skipping patches outside its current prefix.
        patch_env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(out))
        subprocess.run(['git', 'apply', str(out / 'Resources/MuPatches' / patch)],
                       cwd=out / 'Mu_Basecore', env=patch_env, check=True)
        subprocess.run(['git', 'apply', '--reverse', '--check', str(out / 'Resources/MuPatches' / patch)],
                       cwd=out / 'Mu_Basecore', env=patch_env, check=True)
    local_patch = ROOT / 'uefi/lemonades/mu-probe.patch'
    local_env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(out.parent))
    subprocess.run(['git', 'apply', str(local_patch)], cwd=out, env=local_env, check=True)
    subprocess.run(['git', 'apply', '--reverse', '--check', str(local_patch)], cwd=out, env=local_env, check=True)
    init_patch = ROOT / 'uefi/lemonades/mu-initialization.patch'
    subprocess.run(['git', 'apply', str(init_patch)], cwd=out, env=local_env, check=True)
    subprocess.run(['git', 'apply', '--reverse', '--check', str(init_patch)], cwd=out, env=local_env, check=True)
    hob_patch = ROOT / 'uefi/lemonades/mu-hob.patch'
    subprocess.run(['git', 'apply', str(hob_patch)], cwd=out, env=local_env, check=True)
    subprocess.run(['git', 'apply', '--reverse', '--check', str(hob_patch)], cwd=out, env=local_env, check=True)
    shim_patch = ROOT / 'uefi/lemonades/mu-shim.patch'
    subprocess.run(['git', 'apply', str(shim_patch)], cwd=out, env=local_env, check=True)
    subprocess.run(['git', 'apply', '--reverse', '--check', str(shim_patch)], cwd=out, env=local_env, check=True)
    conf = out / 'Conf'
    conf.mkdir()
    for name in ['tools_def', 'build_rule', 'target']:
        shutil.copyfile(out / 'Mu_Basecore/BaseTools/Conf' / (name + '.template'), conf / (name + '.txt'))
    (out / 'build-inputs.json').write_text(json.dumps({'revisions': REPOS, 'upstream_patches': patches,
        'probe_patch_sha256': hashlib.sha256(local_patch.read_bytes()).hexdigest(),
        'initialization_patch_sha256': hashlib.sha256(init_patch.read_bytes()).hexdigest(),
        'hob_patch_sha256': hashlib.sha256(hob_patch.read_bytes()).hexdigest(),
        'shim_patch_sha256': hashlib.sha256(shim_patch.read_bytes()).hexdigest(),
        'overlay_files_sha256': {str(p.relative_to(args.overlay)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted(args.overlay.rglob('*')) if p.is_file()},
        'overlay': str(args.overlay.resolve()), 'scope': 'UEFI probe only; stock binaries unpatched'}, indent=2) + '\n')
    print(out)


if __name__ == '__main__': main()
