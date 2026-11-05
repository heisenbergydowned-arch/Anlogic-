"""Vendor BootGen, preserving exact currently installed PS payloads and boot fields."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
FPGA=ROOT.parent/'r46_temperature_pwm_p39_20261103'
PREVIOUS=ROOT.parent/'r46_temperature_no_current_trip_p50_20261103'
WORK=Path('/Users/heisenberg/Documents/Codex/cabinet-cooling')
sys.path.insert(0,str(WORK))
from vm_sources import guest_python
INSPECT=WORK/'board_work/20261022_single_s4b_deploy/package_boot.py'
INSPECT_SHA='eef8fdd80affde2b0795a7727cc5d7ead3baeee5c94089c2b8b5c043450ffd79'
BOOT_SHA='970d51def42df5bcd9cee18e197cd33dc5505dffe5bcdb314294f76d50607c82'
VENDOR_SHA='f00f16fbc489004309da7d99cfdda94d16daca05dc0ea65f838d3dff299683d8'
PS={'fsbl.from-card.elf':'b15fd97caf73203485cc4500fe2f36e5990ef5a5067016471848c63605caf57f',
    'u-boot.from-card.elf':'58b0dd5c4f4ee697540c3e43c8dd80bbc3d11c3a952728cecc3fed90d81710c3'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
shared=lambda p:'//Mac/Home/'+str(p.resolve().relative_to(Path.home()))

def main(action):
    assert sha(INSPECT)==INSPECT_SHA and sha(PREVIOUS/'boot_package_candidate/BOOT.bin')==BOOT_SHA
    spec=importlib.util.spec_from_file_location('boot_inspector',INSPECT)
    inspector=importlib.util.module_from_spec(spec);spec.loader.exec_module(inspector)
    before,parts=inspector.inspect(PREVIOUS/'boot_package_candidate/BOOT.bin')
    if action!='candidate':raise ValueError('candidate only')
    bundle=ROOT/'reports/build_008'
    collection=json.loads((bundle/'validation.json').read_text())
    assert collection['status']=='BUILT_P52_ALARM_ONLY_PWM'
    bit=bundle/'cooling_link.bit';assert sha(bit)==collection['bit_sha256']
    replay=json.loads((ROOT/'reports/saved_route_check/validation.json').read_text())
    assert replay['status']=='PASS_RELOADED_DB_REPRODUCES_ALL_LOGIC_AND_BITSTREAM_PAYLOAD'
    assert replay['bit_sha256']==collection['bit_sha256']
    plan=json.loads((ROOT/'eco_plan.json').read_text())
    assert collection['plan_sha256']==sha(ROOT/'eco_plan.json')
    assert collection['candidate_db_sha256']==plan['candidate_db_sha256']
    assert collection['physical_changes_verified'] and collection['adc_sdc_unchanged']
    assert plan['setup_wns_ns']==-0.008 and plan['timing_pass'] is False
    assert plan['rtl_sha256']==sha(ROOT/'fpga/src/control/temperature_pwm.v')
    native_proof=dict(validation_sha256=sha(bundle/'validation.json'),eco_plan_sha256=sha(ROOT/'eco_plan.json'),saved_route_verification_sha256=sha(ROOT/'reports/saved_route_check/validation.json'),source_setup_wns_ns=-.008,timing_pass=False)
    baseline=json.loads((FPGA/'boot_package_baseline_002/validation.json').read_text())
    assert baseline['status']=='PASS_BASELINE_REPRODUCED_PS_UNCHANGED'
    assert all(inspector.inspect(FPGA/'boot_package_baseline_002/BOOT.bin')[1][i]==parts[i] for i in (0,2))
    output=ROOT/'boot_package_candidate';output.mkdir(exist_ok=False)
    params=dict(bit=shared(bit),bit_sha=sha(bit),inputs=shared(WORK/'boot_work/20261011_235506/packaging_inputs'),
                ps=PS,vendor_sha=VENDOR_SHA,output=shared(output),
                guest='C:/cabinet_boot_work/p52_alarm_only_pwm_001')
    code='params='+repr(params)+'\n'+r'''
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
'''
    (output/'executed_guest.py').write_text(code)
    provenance=json.loads(guest_python(code))
    after,new=inspector.inspect(output/'BOOT.bin')
    assert provenance['boot_sha256']==sha(output/'BOOT.bin')
    assert before[0x60:0x9c]==after[0x60:0x9c], 'Critical ROM/FSBL header changed'
    assert len(parts)==len(new)==3
    for i,(old,p) in enumerate(zip(parts,new)):
        assert all(old[k]==p[k] for k in ('attributes','entry','load'))
        if i!=1:assert old==p,'PS payload changed'
    assert inspector.swap32(bit.read_bytes().split(b'\n\n',1)[1])==new[1]['payload']
    assert action=='candidate'
    result=dict(status='P52_ALARM_ONLY_PWM_BOOT_PS_UNCHANGED_NOT_FLASHED',
        old_boot_sha256=BOOT_SHA,boot_sha256=sha(output/'BOOT.bin'),bit_sha256=sha(bit),
        provenance=provenance,native_proof=native_proof,all_partition_crc_sha_verified=True,
        fsbl_uboot_unchanged=True,kernel_changes=False,board_written=False,timing_pass=False,user_authorized_setup_wns_ns=-0.008)
    (output/'validation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main(sys.argv[1])
