from pathlib import Path,PureWindowsPath
import sys,json,hashlib
E=Path(__file__).resolve().parent;C=Path('/Users/heisenberg/Documents/Codex/cabinet-cooling/fpga_work/adc_reset_w9_20261023/release_r46_truthful_20261101')
sys.path.insert(0,str(C.parents[2]));from vm_sources import guest_python
prior=json.loads((C/'reports/r46_actual_sensors_hmi/arm64/validation.json').read_text())
source=E/'software_p5/linux/hmi_daily/dashboard.c';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan={'source':str(PureWindowsPath(r'\\Mac\Home',*source.relative_to(Path.home()).parts)),'source_sha256':sha(source),'output':str(PureWindowsPath(r'\\Mac\Home',*(E/'hmi_arm64_r2').relative_to(Path.home()).parts)),'prior':prior}
code=r'''from pathlib import Path
import json,hashlib,subprocess,shutil,re
p=json.loads(PLAN);prior=p['prior'];sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
old=Path(r'C:\Users\heisenberg\FPGA_builds\hmi_arm64_r46_actual_sensors_p4');root=Path(r'C:\Users\heisenberg\FPGA_builds\hmi_arm64_r46_normal_npu_p5_r2');dest=Path(p['output'])
assert not root.exists() and not dest.exists();root.mkdir();dest.mkdir()
compiler=Path(prior['compiler']);assert sha(compiler)==prior['compiler_sha256']
objects=[]
for name,h in prior['shared_library_object_sha256'].items():
 f=old/'objects'/name;assert sha(f)==h;objects.append(f)
source=root/'dashboard.c';shutil.copyfile(p['source'],source);assert sha(source)==p['source_sha256']
flags=['-O2','-fPIE','-std=c99','-Wall','-Wextra','-Werror','-ffunction-sections','-fdata-sections','-DLV_CONF_INCLUDE_SIMPLE','-D_DEFAULT_SOURCE','-I'+str(old/'hmi'),'-I'+str(old/'vendor')]
commands=[[str(compiler)]+flags+['-c',str(source),'-o',str(root/'dashboard.o')]]
response=root/'objects.rsp';response.write_text('\n'.join('"'+f.as_posix()+'"' for f in objects+[root/'dashboard.o']))
commands.append([str(compiler),'-pie','-Wl,--gc-sections,-z,text,-z,relro,-z,now,-z,noexecstack','-o',str(root/'cabinet_dashboard'),'@'+str(response),'-lm','-pthread'])
for i,command in enumerate(commands):
 r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,timeout=180);(root/('build%d.log'%i)).write_text(r.stdout);assert r.returncode==0 and not r.stdout,r.stdout
elf=subprocess.check_output([str(compiler.with_name('aarch64-linux-gnu-readelf.exe')),'-W','-h','-l','-d','-V',str(root/'cabinet_dashboard')],universal_newlines=True)
assert 'AArch64' in elf and re.search(r'Type:\s+DYN',elf) and 'TEXTREL' not in elf and 'BIND_NOW' in elf
assert set(re.findall(r'GLIBC_\d+\.\d+',elf))=={'GLIBC_2.17'}
(root/'elf.log').write_text(elf)
r={'status':'PASS_ARM64_P5_HMI_BUILD','binary_sha256':sha(root/'cabinet_dashboard'),'source_sha256':sha(source),'compiler_sha256':sha(compiler),'reused_verified_library_objects':len(objects),'warnings':0,'board_executed':False,'commands':commands}
(root/'validation.json').write_text(json.dumps(r,indent=2)+'\n')
for f in root.iterdir():
 if f.is_file():shutil.copyfile(f,dest/f.name)
print(json.dumps(r))
'''.replace('PLAN',repr(json.dumps(plan)))
print(guest_python(code))
