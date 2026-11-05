"""Audit new candidate operator scope without granting deployment qualification."""
# Frozen from tools/audit_classifier.py in R46 P14; source SHA-256:
# de152c0a57778b0aa8c0c60fab2e4416521295081312b16d9dd52514781b2d97
import argparse
import hashlib
import json
from pathlib import Path
if __package__:
    from .utf8_io import configure_stdio
else:
    from utf8_io import configure_stdio
import onnx
from onnx import helper, numpy_helper, TensorProto


def audit(data):
    model = onnx.load_model_from_string(data)
    if any(tensor.data_location != TensorProto.DEFAULT for tensor in model.graph.initializer):
        raise ValueError('External model data is not admissible')
    onnx.checker.check_model(model)
    allowed = {'Gemm', 'QuantizeLinear', 'DequantizeLinear', 'Relu'}
    forbidden = sorted({node.op_type for node in model.graph.node} - allowed)
    if forbidden or any(node.domain not in ('', 'ai.onnx') for node in model.graph.node):
        raise ValueError('Unsupported restricted-profile operator')
    for tensors, shape in [(model.graph.input, [1, 39]), (model.graph.output, [1, 5])]:
        if len(tensors) != 1 or tensors[0].type.tensor_type.elem_type != TensorProto.UINT8 or [dimension.dim_value for dimension in tensors[0].type.tensor_type.shape.dim] != shape:
            raise ValueError('Exact batch-one UINT8 tensor contract required')
    constants = {tensor.name: tensor for tensor in model.graph.initializer}
    producers = {output: node for node in model.graph.node for output in node.output}
    dimensions, transposes = [], []
    for node in model.graph.node:
        if node.op_type != 'Gemm':
            continue
        attributes = {value.name: helper.get_attribute_value(value) for value in node.attribute}
        if attributes.get('transA', 0) != 0 or attributes.get('transB', 0) != 1 or attributes.get('alpha', 1) != 1 or attributes.get('beta', 1) != 1:
            raise ValueError('SDK requires transB=1 and unscaled Gemm')
        weights = producers.get(node.input[1])
        if weights is None or weights.op_type != 'DequantizeLinear' or any(name not in constants for name in weights.input):
            raise ValueError('Constant per-tensor QDQ weights required')
        if any(numpy_helper.to_array(constants[name]).size != 1 for name in weights.input[1:]):
            raise ValueError('Per-axis quantization requires a separate SDK audit')
        matrix = numpy_helper.to_array(constants[weights.input[0]])
        dimensions.append(list(matrix.shape[::-1]));transposes.append(1)
    if dimensions != [[39, 32], [32, 16], [16, 5]]:
        raise ValueError('Only the reviewed three-layer classifier is supported')
    return dict(schema='cabinet-candidate-graph-v1', model_sha256=hashlib.sha256(data).hexdigest(),
                hardware_profile='DR1M90_GEMM39_POOL_UP_OFF_V1', dimensions=dimensions,
                transB=transposes, forbidden_ops=[], qualified=False, hardware_executed=False)


if __name__ == '__main__':
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite an audited artifact')
    args.output.write_text(json.dumps(audit(args.model.read_bytes()), indent=2) + '\n', encoding='utf-8')
