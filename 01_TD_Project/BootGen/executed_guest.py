params={'bit': '//Mac/Home/Documents/Codex/2026-11-01/kan/work/r46_alarm_only_pwm_p52_20261103/reports/build_008/cooling_link.bit', 'bit_sha': '2a09883497ca92c6e4b82c850047eeb7891a5b5f256a769b39609f4256fbb268', 'inputs': '//Mac/Home/Documents/Codex/cabinet-cooling/boot_work/20261011_235506/packaging_inputs', 'ps': {'fsbl.from-card.elf': 'b15fd97caf73203485cc4500fe2f36e5990ef5a5067016471848c63605caf57f', 'u-boot.from-card.elf': '58b0dd5c4f4ee697540c3e43c8dd80bbc3d11c3a952728cecc3fed90d81710c3'}, 'vendor_sha': 'f00f16fbc489004309da7d99cfdda94d16daca05dc0ea65f838d3dff299683d8', 'output': '//Mac/Home/Documents/Codex/2026-11-01/kan/work/r46_alarm_only_pwm_p52_20261103/boot_package_candidate', 'guest': 'C:/cabinet_boot_work/p52_alarm_only_pwm_001'}

import hashlib,json,shutil,subprocess
from pathlib import Path
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
stage=Path(params['guest']);out=Path(params['output']);stage.mkdir(parents=True,exist_ok=False)
vendor=Path('C:/Anlogic/FD_2026.1_SP1/tools/bootgen/albg1.exe')
assert sha(vendor)==params['vendor_sha']
for name,pin in params['ps'].items():
 src=Path(params['inputs'])/name;assert sha(src)==pin;shutil.copy2(src,stage/name)
src=Path(params['bit']);assert sha(src)==params['bit_sha'];shutil.copy2(src,stage/'cooling_link.bit')
bif='the_ROM_image:\n{\n [bootloader, destination_cpu = apu-0, destination_device = ps, checksum = sha2] fsbl.from-card.elf\n [partition_owner = fsbl, destination_cpu = apu-0, destination_device = pl, checksum = sha2, load = 0x00200000] cooling_link.bit\n [partition_owner = fsbl, destination_cpu = apu-0, destination_device = ps, checksum = sha2] u-boot.from-card.elf\n}\n'
(stage/'boot.bif').write_text(bif)
p=subprocess.run([str(vendor),'-image','boot.bif','-o','BOOT.bin','-w','on'],cwd=stage,capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
(out/'bootgen.log').write_text(p.stdout+p.stderr)
assert p.returncode==0 and (stage/'BOOT.bin').is_file()
for n in ('BOOT.bin','boot.bif'):shutil.copy2(stage/n,out/n)
print(json.dumps(dict(vendor_sha256=sha(vendor),boot_sha256=sha(stage/'BOOT.bin'),input_bit_sha256=params['bit_sha'],ps_inputs=params['ps'])))
