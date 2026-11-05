"""Save trained candidates without selecting them or touching the NPU service."""
import json
from pathlib import Path

from .baseline_store import durable_save, file_sha, storage_status

POLICY = Path('/etc/cabinet/npu-deployment-policy.json')
STAGED = 'TRAINED_SAVED_NOT_DEPLOYED'


def activation_allowed(job=None, path=POLICY):
    if (job or {}).get('auto_deploy') is False:
        return False
    if not path.exists():
        return True
    value = json.loads(path.read_text(encoding='utf-8'))
    if (value.get('schema') != 'cabinet-npu-deployment-policy-v1' or
            value.get('mode') not in ('STAGE_ONLY', 'AUTO_DEPLOY')):
        raise ValueError('INVALID_NPU_DEPLOYMENT_POLICY')
    return value['mode'] == 'AUTO_DEPLOY' and value.get('automatic_activation') is True


def stage_candidate(store, job, archive_pin, manifest_pin):
    """Caller holds the job lock. No model env, service, or device is changed."""
    folder = store.folder(job['id'])
    if job.get('state') == 'COMPLETED' and job.get('result', {}).get('status') == STAGED:
        result = job['result']
        if (result['archive_sha256'], result['manifest_sha256']) != (archive_pin, manifest_pin):
            raise ValueError('STAGED_CANDIDATE_RETRY_PINS_CHANGED')
        if file_sha(Path(result['bundle_path']) / 'manifest.json') != manifest_pin:
            raise ValueError('STAGED_CANDIDATE_CHANGED')
        return dict(state='COMPLETED', result=result)
    if job.get('state') != 'HOST_VALIDATED':
        raise ValueError('HOST_VALIDATED_CANDIDATE_REQUIRED_FOR_STAGING')
    store.check(job)
    archive = folder / 'candidate.tar.gz'
    if file_sha(archive) != archive_pin:
        raise ValueError('STAGED_ARCHIVE_PIN_CHANGED')
    env_pin = file_sha(store.env)
    candidate = folder / 'staged-bundle'
    labeled = job.get('kind') == 'labeled_classifier'
    if labeled:
        from labeled_npu.deploy import unpack, validate_candidate
    else:
        from .learning_deploy import unpack, validate_candidate
    if not candidate.exists():
        unpack(archive, candidate, archive_pin)
    checked = validate_candidate(store, job, candidate, manifest_pin)
    bundle, training = (checked, checked.validation) if labeled else checked
    if file_sha(store.env) != env_pin:
        raise ValueError('ACTIVE_MODEL_CHANGED_DURING_STAGING')
    storage = storage_status(candidate)
    if storage.get('persistent') is not True:
        raise ValueError('PERSISTENT_CANDIDATE_STORAGE_REQUIRED')
    result = dict(status=STAGED, deployed=False, saved=True,
                  saved_on_sd=storage.get('is_sd') is True,
                  label=job.get('label', 'normal'), labels=bundle.manifest.get('labels', ['normal']),
                  model_id=bundle.manifest['model_id'], manifest_sha256=manifest_pin,
                  archive_sha256=archive_pin, bundle_path=str(candidate),
                  training=training, hardware_validation='NOT_RUN',
                  awaiting='ALL_CONDITIONS_THEN_EXPLICIT_BATCH_DEPLOYMENT',
                  active_env_sha256=env_pin, controls_changed=False,
                  startup_selection_changed=False, npu_service_restarted=False)
    durable_save(folder / 'staged-candidate.json', result)
    job.update(state='COMPLETED', result=result, auto_deploy=False,
               deployment_policy='STAGE_ONLY', progress_percent=100,
               progress_detail='训练完成，候选已保存到 SD 卡，等待统一部署',
               updated_at=store.clock())
    durable_save(folder / 'job.json', job)
    return dict(state='COMPLETED', result=result)
