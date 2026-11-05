import json,os,subprocess,sys,time
from pathlib import Path
r=Path(__file__).resolve().parent
env=os.environ.copy();env['PYTHONPATH']=str(r/'linux')+os.pathsep+str(r/'host')
checks={}
for name in ('train_normal.py','train_labeled.py','compile_alnpu_bundle.py','compile_labeled_bundle.py'):
 p=subprocess.run([sys.executable,'-B',str(r/'host'/name),'--help'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
 checks[name]={'returncode':p.returncode,'stderr':p.stderr.decode('utf-8','replace')[-1000:]}
 if p.returncode:
  (r/'startup-preflight.json').write_text(json.dumps({'ok':False,'checks':checks,'time':time.time()},indent=2));raise SystemExit(p.returncode)
(r/'startup-preflight.json').write_text(json.dumps({'ok':True,'checks':checks,'time':time.time()},indent=2))
os.execv(sys.executable,[sys.executable,'-B',str(r/'host/worker.py')]+sys.argv[1:])
