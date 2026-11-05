from pathlib import Path,PureWindowsPath
import json,sys
E=Path(__file__).resolve().parent;R=Path('/Users/heisenberg/Documents/Codex/cabinet-cooling');sys.path.insert(0,str(R));from vm_sources import guest_python
path=str(PureWindowsPath(r'\\Mac\Home',*E.relative_to(Path.home()).parts))
code=r'''from pathlib import Path
import subprocess,hashlib,json,shutil
p=Path(SHARED);compiler=Path(r'C:\Anlogic\FD_2026.1_SP1\toolchain\gcc\aarch64_linux\bin\aarch64-linux-gnu-g++.exe');sdk=Path(r'C:\Users\heisenberg\FPGA_builds\cabinet_local_link_r46_truthful_20261101_001\sdk');out=p/'native/sdk_model_check'
command=[str(compiler),'-O2','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(sdk/'include'),str(p/'native/sdk_model_check.cpp'),'-L'+str(sdk/'lib'),'-Wl,-rpath-link,'+str(sdk/'lib'),'-larmnn','-larmnnOnnxParser','-pthread','-ldl','-o',str(out)]
r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,timeout=120);assert r.returncode==0,r.stdout
print('PASS_OFFLINE_SDK_MODEL_CHECK_BUILD')
'''.replace('SHARED',repr(path))
print(guest_python(code))
