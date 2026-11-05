"""User-declared condition learning, with no manual exports or model uploads."""
import hashlib
import json
import shutil
import tarfile
import time
from pathlib import Path


def save(path, value):
    temporary = path.with_suffix('.next')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_capture(archive, destination):
    """Only the finite, reviewed export layout may cross the SSH boundary."""
    files = {'sessions.json', 'learning.json'}
    files.update('captures/episode/'+name for name in
                 ('session.json', 'feature_contract.json', 'frames.jsonl', 'summary.json'))
    directories = {'captures', 'captures/episode'}
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        names = [m.name for m in members]
        if len(set(names)) != len(names) or set(names)-files-directories or files-set(names):
            raise ValueError('LABELED_CAPTURE_EXPORT_LAYOUT_INVALID')
        if any(not ((m.isfile() and m.name in files) or (m.isdir() and m.name in directories)) for m in members):
            raise ValueError('LABELED_CAPTURE_EXPORT_REGULAR_FILES_REQUIRED')
        if sum(m.size for m in members) > 128*1024*1024:
            raise ValueError('LABELED_CAPTURE_EXPORT_TOO_LARGE')
        destination.mkdir(exist_ok=False)
        for member in members:
            target = destination/member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as reader, target.open('xb') as writer:
                    shutil.copyfileobj(reader, writer)


def run_labeled_job(worker, job):
    identity = job['id']
    folder = worker.root/identity
    folder.mkdir(mode=0o700, exist_ok=False)
    save(folder/'request.json', job)
    def call(operation, **values):
        return worker.call(operation, channel='labeled', job_id=identity, **values)
    def train(script, args, log):
        worker.train(script, args, folder/log, identity, channel='labeled')
    try:
        call('capture-begin', split='episode')
        while True:
            if worker.stop.wait(3):
                raise RuntimeError('Worker stopping')
            progress = call('capture-poll')
            save(folder/'progress.json', progress)
            if progress['state'] == 'CAPTURE_SAVED':
                break
        exported = call('export')
        remote = '/var/lib/cabinet/npu-learning/jobs/'+identity+'/captures.tar.gz'
        if exported['path'] != remote:
            raise ValueError('Unexpected labeled capture export path')
        archive = folder/'captures.tar.gz'
        worker.copy(worker.target+':'+remote, str(archive))
        if sha(archive) != exported['sha256']:
            raise ValueError('Labeled capture transfer checksum failed')
        data = folder/'data'
        extract_capture(archive, data)
        train('labeled_dataset.py', ['--export',str(data),'--registry',str(worker.root/'labeled-datasets'),
                                    '--output',str(folder/'corpus.json')], 'registration.log')
        corpus = json.loads((folder/'corpus.json').read_text(encoding='utf-8'))
        progress = call('finalize-collection', corpus_summary=corpus)
        save(folder/'progress.json', progress)
        if progress['state'] == 'COLLECTED_WAITING_DATA':
            save(folder/'result.json', progress)
            print('LABELED_DATA_COLLECTED '+identity, flush=True)
            return
        if progress['state'] != 'TRAINING' or corpus['status'] != 'READY_TO_TRAIN':
            raise ValueError('Labeled dataset readiness disagreement')
        train('train_labeled.py', ['--dataset',corpus['dataset_dir'],'--output',str(folder/'reference')], 'training.log')
        train('compile_labeled_bundle.py', ['--reference',str(folder/'reference'),'--output',str(folder/'candidate')], 'compile.log')
        candidate = folder/'candidate'
        receipt = json.loads((candidate/'receipt.json').read_text(encoding='utf-8'))
        manifest = json.loads((candidate/'manifest.json').read_text(encoding='utf-8'))
        names = set(manifest['artifacts_sha256'])|{'manifest.json','training_validation.json','receipt.json'}
        if any(Path(name).name != name or (candidate/name).is_symlink() or not (candidate/name).is_file() for name in names):
            raise ValueError('Labeled candidate regular flat artifacts required')
        with tarfile.open(folder/'candidate.tar.gz','w:gz') as output:
            for name in sorted(names):
                output.add(candidate/name, arcname=name)
        call('host-validated')
        worker.copy(str(folder/'candidate.tar.gz'),worker.target+':/var/lib/cabinet/npu-learning/jobs/'+identity+'/candidate.tar.gz')
        call('deploy-start', archive_sha256=sha(folder/'candidate.tar.gz'), manifest_sha256=receipt['manifest_sha256'])
        deadline = time.monotonic()+480
        while True:
            try:
                result = call('deployment-status')
            except Exception:
                if time.monotonic()>deadline:
                    raise
                worker.stop.wait(3)
                continue
            if result['state']=='COMPLETED':
                break
            if result['state'] in ('FAILED','INTERRUPTED','CANCELLED','RECOVERY_REQUIRED'):
                raise RuntimeError(result.get('error',result['state']))
            if time.monotonic()>deadline:
                raise RuntimeError('Board deployment deadline exceeded; inspect durable board transaction')
            worker.stop.wait(3)
        save(folder/'result.json',result)
        print('LABELED_LEARNING_COMPLETED '+identity,flush=True)
    except Exception as error:
        save(folder/'failure.json',dict(error=str(error),at=time.time()))
        try:
            call('failed',error=str(error))
        except Exception as reporting:
            save(folder/'reporting-failure.json',dict(error=str(reporting)))
        print('LABELED_LEARNING_FAILED '+identity+' '+str(error),flush=True)
