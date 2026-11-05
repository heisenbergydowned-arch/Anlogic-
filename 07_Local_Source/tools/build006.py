import json,hashlib,subprocess,time,datetime,shutil,traceback
from pathlib import Path
from eco_review import parse_cell
ROOT=Path(__file__).resolve().parents[1]
MAC=Path('//Mac/Home/Documents/Codex/2026-11-01/kan/work/r46_alarm_only_pwm_p52_20261103')
PARENT=Path('C:/Users/heisenberg/FPGA_builds/cabinet_temperature_no_current_trip_p50_20261103/build_003')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
out=ROOT/'build_006';out.mkdir();state=dict(status='RUNNING',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),timing_pass=False,source_setup_wns_ns=-.008,route_scope='TWO_INDICATOR_NETS_ONLY');write(out/'validation.json',state);p=None
try:
 spec=read(ROOT/'build002_spec.json');pins=read(ROOT/'build006_pins.json')
 def verify():
  for n,h in pins.items():assert sha(ROOT/n)==h,n
  assert sha(PARENT/'no_current_threshold.pr.db')=='63001f14c94550c13e7e8226a92eee287dd66fd9392842ffbc93184e51ea7cd6'
 verify()
 with (out/'native_console.log').open('w') as log:
  p=subprocess.Popen(['C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe',(ROOT/'tools/build006.tcl').as_posix()],cwd=out,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  state['pid']=p.pid;write(out/'validation.json',state);deadline=time.monotonic()+540;approved=False
  while p.poll() is None:
   text=(out/'native_console.log').read_text(errors='replace')
   if 'P52_LOCAL_PATCH_EXPORTED' in text and not approved:
    assert 'ERROR:' not in text and 'coredump' not in text and 'MPNR Save failed' not in text
    changes={}
    for n,s in spec.items():
     def parsed(marker):return parse_cell(text.split(marker+' '+n+'\n',1)[1].split('P52_CELL_END',1)[0])
     a,b=parsed('P52_BEFORE'),parsed('P52_AFTER')
     assert json.loads(json.dumps(a))==s['base'],n
     expected=json.loads(json.dumps(a));expected['attrs'].update(s['changes'])
     assert json.loads(json.dumps(b))==expected,n
     changes[n]=dict(before=a,after=b)
    a=parse_cell(text.split('P52_OLD_LED_BEFORE\n',1)[1].split('P52_OLD_LED_END',1)[0])
    b=parse_cell(text.split('P52_OLD_LED_AFTER\n',1)[1].split('P52_OLD_LED_END',1)[0])
    expected=json.loads(json.dumps(a));expected['outputs']['ofa'][1]='Nil'
    assert json.loads(json.dumps(b))==expected, 'Unexpected old LED source modification'
    assert 'Manual mode try route net O_led4_alm_dup_3 succeeded.' in text
    assert 'P52_MANUAL_COMMIT_RETURNED' in text and 'start command "mpnr_save_revert -save"' in text
    assert 'start command "route -eco"' not in text and 'start command "route -incremental"' not in text
    assert text.count('start command "mpnr_route_net -net O_led4_alm_dup_3"')==1
    assert sha(out/'after.adc')==sha(PARENT/'after.adc'), 'ADC changed'
    assert sha(out/'after.sdc')==sha(PARENT/'after.sdc'), 'SDC changed'
    plan=dict(status='REVIEWED_SIX_LUT_CHANGES_AND_RED_LED_NET_ONLY',physical_changes=changes,parent_db_sha256=sha(PARENT/'no_current_threshold.pr.db'),candidate_db_sha256=sha(out/'alarm_only.pr.db'),adc_sha256=sha(out/'after.adc'),sdc_sha256=sha(out/'after.sdc'),rtl_sha256=pins['fpga/src/control/temperature_pwm.v'],subsys_sha256=pins['fpga/src/acq/subsys_acq.v'],setup_wns_ns=-.008,timing_pass=False,timing_exception_previously_authorized=True,full_sta_repeated=False,routed_nets_changed=['system/u_subsys_acq/u_control/physical_level_b1_n','O_led4_alm_dup_3'],clock_constraints_changed=False)
    write(out/'eco_plan.json',plan);verify();(out/'changes.pass').write_text('Six LUT changes, one indicator connection, two indicator routes verified\n');approved=True
   if 'ERROR:' in text or 'coredump' in text or 'MPNR Save failed' in text:raise RuntimeError('Native tool failed: '+repr([line for line in text.splitlines() if 'ERROR:' in line or 'MPNR Save failed' in line or 'coredump' in line])+text[-500:])
   if time.monotonic()>deadline:raise RuntimeError('Native tool deadline')
   time.sleep(.5)
 assert p.returncode==0 and approved
 text=(out/'native_console.log').read_text();assert text.splitlines().count('P52_BITGEN_COMPLETE')==1
 assert 'ERROR:' not in text and 'coredump' not in text and 'MPNR Save failed' not in text;verify()
 state.update(status='BUILT_P52_ALARM_ONLY_PWM',bit_sha256=sha(out/'cooling_link.bit'),bit_bytes=(out/'cooling_link.bit').stat().st_size,candidate_db_sha256=plan['candidate_db_sha256'],plan_sha256=sha(out/'eco_plan.json'),physical_changes_verified=True,properties_verification='SIX_LUT_CHANGES_SINGLE_RED_FLASH_NET_EXPLICIT_MPNR_COMMIT_NATIVE_BITGEN_CHECK_PASS',adc_sdc_unchanged=True)
except BaseException as e:
 if p is not None and p.poll() is None:p.terminate();p.wait(timeout=20)
 state.update(status='FAIL',error=repr(e),traceback=traceback.format_exc())
state['completed_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();write(out/'validation.json',state)
dest=MAC/'reports/build_006';dest.mkdir(exist_ok=True)
for f in out.iterdir():
 if f.is_file() and f.suffix not in ('.db','.vnew','.dmp'):shutil.copy2(f,dest/f.name)
if state['status'].startswith('BUILT_'):shutil.copy2(out/'eco_plan.json',MAC/'eco_plan.json')
print(json.dumps(state))
