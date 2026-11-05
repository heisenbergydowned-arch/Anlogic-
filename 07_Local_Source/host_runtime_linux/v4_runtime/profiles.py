"""Pinned model scope for the pool/upsample-free R30 FPGA profile."""
PROFILE = 'DR1M90_GEMM39_POOL_UP_OFF_V1'
PL_BUILD_ID = 0x202610f7
MODEL_SHA256 = frozenset({
    '6268d7b997fed391cfa95b6704bc38f88bdfacb69a09865e6f3190029707618c',
    'b7fd8f478aa366f0587992f318afc12249ad5ee3aa1b8a4799b8c60a9b997d4b',
})


def validate_profile(manifest, reviewed_model_sha256=None):
    profile = manifest.get('hardware_profile')
    if profile is None:
        if manifest.get('compatible_pl_build_ids') != [0x202610f4]:
            raise ValueError('Legacy PL compatibility was not frozen')
        return None
    if profile != PROFILE or manifest.get('compatible_pl_build_ids') != [PL_BUILD_ID]:
        raise ValueError('Unknown or mismatched restricted FPGA profile')
    if manifest.get('native_abi') != 3 or manifest.get('execution_model') != 'ALNPU_LOGITS_PS_SOFTMAX':
        raise ValueError('Restricted profile requires the explicit ABI3 logits contract')
    hashes = manifest.get('artifacts_sha256')
    if type(hashes) is not dict or (hashes.get('model_logits_u8.onnx') not in MODEL_SHA256 and
                                   (reviewed_model_sha256 is None or hashes.get('model_logits_u8.onnx') != reviewed_model_sha256)):
        raise ValueError('Model has not been audited for the restricted FPGA operator scope')
    return PROFILE


def verify_native_profile(info, bundle):
    expected = getattr(bundle, 'hardware_profile', None)
    if type(info) is not dict or info.get('hardware_profile') != expected or expected != PROFILE:
        raise ValueError('Native adapter and model hardware profile mismatch')
    if info.get('compatible_pl_build_ids') != [PL_BUILD_ID]:
        raise ValueError('Native adapter targets a different FPGA build')
