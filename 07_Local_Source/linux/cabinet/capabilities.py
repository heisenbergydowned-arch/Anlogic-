"""Implementation scope, deliberately separate from qualification evidence."""


def implementation_scope(claims=None):
    facts=dict(single_fan_cascade=True,independent_actuators=1,
        temperature_loop_processor='PS',rpm_loop_processor='PL',
        classification_pipeline='ALNPU_FIVE_CLASS_WITH_PS_SOFTMAX',
        grade_runtime='PS_AUXILIARY_LINEAR_HEAD',npu_multitask_deployed=False,
        multiple_independent_control_loops=False,real_model_qualified=False,
        real_rul_below_10_percent=False,board_accepted=False,advanced_all_accepted=False)
    if claims is not None:
        if type(claims) is not dict or set(claims)-set(facts):raise ValueError('Unknown implementation claim')
        if any(type(value) is not type(facts[name]) or value!=facts[name] for name,value in claims.items()):
            raise ValueError('Claim exceeds the implemented and qualified scope')
    return dict(schema='cabinet-implementation-scope-v1',implementation=facts,
        qualification_granted=False,prototype_exports_cannot_activate_models=True,
        scope_decisions=['Retain one physical fan; no fabricated second actuator',
            'Keep PS grade explicitly separate; exported grade ONNX is an unactivated research artifact',
            'Multi-actuator credit and real NPU multi-task execution remain unclaimed'])
