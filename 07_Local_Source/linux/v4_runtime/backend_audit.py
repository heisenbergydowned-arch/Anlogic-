"""Reject backend labels that are not supported by the optimized native graph.

This is a runtime backend-assignment check, not physical/model qualification.
Unknown graph formats fail closed until reviewed against the installed SDK.
"""
import hashlib
import re


def verify_alnpu_graph(info, graph):
    if info.get('backend_audit_schema') != 'cabinet-alnpu-graph-v1':
        raise ValueError('Native adapter predates verified backend reporting; rebuild required')
    if info.get('requested_backends') != ['Alnpu']:
        raise ValueError('Alnpu-only backend request required')
    if type(graph) is not str or not 1 <= len(graph) <= 1048576 or not graph.lstrip().startswith('digraph'):
        raise ValueError('Bounded native optimized DOT graph required')
    if re.search(r'\b(?:CpuAcc|CpuRef|GpuAcc|CPUExecutionProvider)\b', graph):
        raise ValueError('Optimized graph contains a CPU/GPU fallback backend')
    labels = graph.replace(r'\n', '\n').replace(r'\l', '\n')
    assignments = re.findall(r'\bbackend(?:Id)?\s*[:=]\s*[\\"\s]*([A-Za-z][A-Za-z0-9_]*)', labels, re.IGNORECASE)
    if not assignments or set(assignments) != {'Alnpu'}:
        raise ValueError('Optimized graph has missing, unknown or non-Alnpu backend assignments')
    return dict(schema='cabinet-alnpu-graph-v1', assigned_backends=['Alnpu'],
                graph_sha256=hashlib.sha256(graph.encode('utf-8')).hexdigest(),
                backend_assignment_verified=True, hardware_qualified=False)
