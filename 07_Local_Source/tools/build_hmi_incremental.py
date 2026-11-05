import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,'/Users/heisenberg/Documents/Codex/cabinet-cooling')
from vm_sources import guest_python
code=r'''
import hashlib,subprocess,shutil,json
from pathlib import Path
base=Path(r'C:\Users\heisenberg\FPGA_builds\cabinet_p46_hmi_20261103_001')
root=Path(r'C:\Users\heisenberg\FPGA_builds\cabinet_p52_hmi_001');root.mkdir()
mac=Path(r'\\Mac\Home\Documents\Codex\2026-11-01\kan\work\r46_alarm_only_pwm_p52_20261103')
compiler=Path(r'C:\Anlogic\FD_2026.1_SP1\toolchain\gcc\aarch64_linux\bin\aarch64-linux-gnu-gcc.exe')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
old=json.loads((base/'validation.json').read_text());assert old['status']=='PASS_ARM64_NATIVE_HMI_LINKED_NOT_EXECUTED_NOT_BOARD_ACCEPTED'
assert sha(base/'cabinet_dashboard')=='be62270fb9e4b8f8119e4c30d7b690044929ee6cc389eae7235644dd81c85b90'
objs=[Path(n.strip().strip('"')) for n in (base/'objects.rsp').read_text().splitlines()];assert len(objs)==old['compiled_sources']==464
pins={str(p):sha(p) for p in objs}
def run(cmd):
 p=subprocess.run(cmd,capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=120)
 assert p.returncode==0 and not p.stdout and not p.stderr,(p.returncode,p.stdout,p.stderr)
run([str(compiler),'-Wl,--gc-sections','-o',str(root/'baseline'), '@'+str(base/'objects.rsp'),'-lm','-pthread'])
assert sha(root/'baseline')==old['binary_sha256'],'Original objects did not reproduce deployed HMI'
source=mac/'linux/hmi_daily/dashboard.c';shutil.copy2(source,root/'dashboard.c')
flags=['-O2','-std=c99','-Wall','-Wextra','-Werror','-ffunction-sections','-fdata-sections','-DLV_CONF_INCLUDE_SIMPLE','-D_DEFAULT_SOURCE','-I'+str(base/'hmi'),'-I'+str(base/'vendor')]
run([str(compiler),*flags,'-c',str(root/'dashboard.c'),'-o',str(root/'dashboard.o')])
new=objs[:-1]+[root/'dashboard.o'];(root/'objects.rsp').write_text('\n'.join('"'+p.as_posix()+'"' for p in new))
run([str(compiler),'-Wl,--gc-sections','-o',str(root/'cabinet_dashboard'),'@'+str(root/'objects.rsp'),'-lm','-pthread'])
assert all(sha(Path(p))==h for p,h in pins.items())
assert sha(source)==sha(root/'dashboard.c')
report=dict(status='PASS_P52_INCREMENTAL_HMI_P46_OBJECTS_REPRODUCED',baseline_sha256=old['binary_sha256'],binary_sha256=sha(root/'cabinet_dashboard'),source_sha256=sha(source),recompiled_units=1,reused_units=463,compiler_sha256=sha(compiler),unchanged_objects_sha256=pins)
(root/'validation.json').write_text(json.dumps(report,indent=2)+'\n');out=mac/'reports/hmi';out.mkdir();shutil.copy2(root/'validation.json',out/'validation.json');shutil.copy2(root/'cabinet_dashboard',mac/'linux/hmi_daily/cabinet_dashboard')
print(json.dumps({k:v for k,v in report.items() if k!='unchanged_objects_sha256'}))
'''
(ROOT/'reports/hmi_build_guest.py').write_text(code)
print(guest_python('import runpy;runpy.run_path('+repr('//Mac/Home/Documents/Codex/2026-11-01/kan/work/r46_alarm_only_pwm_p52_20261103/reports/hmi_build_guest.py')+',run_name="__main__")'))
