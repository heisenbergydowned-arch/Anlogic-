from pathlib import Path,PureWindowsPath
import sys,json,hashlib
E=Path(__file__).resolve().parent;C=Path('/Users/heisenberg/Documents/Codex/cabinet-cooling/fpga_work/adc_reset_w9_20261023/release_r46_truthful_20261101');sys.path.insert(0,str(C.parents[2]));from vm_sources import guest_python
prior=json.loads((C/'native_r46/validation.json').read_text());source=E/'native/normal_reconstruction_trace.cpp'
plan={'source':str(PureWindowsPath(r'\\Mac\Home',*source.relative_to(Path.home()).parts)),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'output':str(PureWindowsPath(r'\\Mac\Home',*(E/'native_offline_r2').relative_to(Path.home()).parts)),'prior':prior}
code=r'''from pathlib import Path
import json,hashlib,shutil,subprocess,re
p=json.loads(PLAN);prior=p['prior'];sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();old=Path(prior['guest_root']);root=Path(r'C:\Users\heisenberg\FPGA_builds\normal_npu_abi39_r2');dest=Path(p['output']);assert not root.exists() and not dest.exists();root.mkdir();dest.mkdir()
compiler=Path(prior['compiler']);assert sha(compiler)==prior['compiler_sha256']
for n,h in prior['sdk_libraries_sha256'].items():assert sha(old/'sdk/lib'/n)==h
source=root/'normal_reconstruction.cpp';shutil.copyfile(p['source'],source);assert sha(source)==p['source_sha256']
command=[str(compiler),'-std=c++17','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off','-shared','-fPIC','-Wl,--no-undefined,-z,relro,-z,now','-Wl,-soname,libnormal_npu.so','-I'+str(old/'sdk/include'),str(source),'-L'+str(old/'sdk/lib'),'-Wl,-rpath-link,'+str(old/'sdk/lib'),'-larmnn','-larmnnOnnxParser','-o',str(root/'libnormal_npu.so')]
r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,timeout=180);(root/'build.log').write_text(r.stdout);assert r.returncode==0 and not r.stdout,r.stdout
elf=subprocess.check_output([str(compiler.with_name('aarch64-linux-gnu-readelf.exe')),'-W','-h','-l','-d','-V',str(root/'libnormal_npu.so')],universal_newlines=True)
assert 'AArch64' in elf and 'TEXTREL' not in elf and 'BIND_NOW' in elf
(root/'elf.log').write_text(elf)
result={'status':'PASS_OFFLINE_ARM64_NATIVE_BUILD_NOT_TARGET_EXECUTED','source_sha256':sha(source),'binary_sha256':sha(root/'libnormal_npu.so'),'compiler_sha256':sha(compiler),'sdk_libraries_sha256':prior['sdk_libraries_sha256'],'sdk_headers_sha256':{str(f.relative_to(old/'sdk/include')):sha(f) for f in (old/'sdk/include').rglob('*') if f.is_file()},'command':command,'previous_target_failure_not_resolved_by_this_build':True}
(root/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
for f in root.iterdir():
 if f.is_file():shutil.copyfile(f,dest/f.name)
print(json.dumps({k:v for k,v in result.items() if k!='sdk_headers_sha256'}))
'''.replace('PLAN',repr(json.dumps(plan)))
print(guest_python(code))
