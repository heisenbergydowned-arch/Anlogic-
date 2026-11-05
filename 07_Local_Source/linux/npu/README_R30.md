# R30 ABI3 adapter

The release adapter is `libedge_npu_logits_ps.so`, built from `edge_npu_logits_ps.cpp`
and `ps_softmax.hpp`. It requires the actual ARM64 SDK_2026.01 ArmNN/ONNX parser.
That SDK exports the CMA API from libarmnn itself; no invented separate CMA library
is required. The supplied cross-link receipt records the exact compiler, SDK, flags,
ELF exports and source hashes. CMake defaults to this ABI3 adapter; the old ABI2
adapter is source-only and opt-in, not a substitute for R30.

The adapter accepts only the fixed R30 GEMM39 profile, returns uint8 logits and
explicitly computes stable PS Softmax. Alnpu is the only requested backend. The
Python loader checks static profile metadata before opening a network, verifies
the new real PL frame identity, and binds the model body hash. A model/scope or
driver failure is an error, never a CPU fallback.

Use the delivered `deployment/npu_accept.py` for opt-in file, graph and golden
stages. Do not enable the legacy service examples. Synthetic model results do not
authorize real control or qualify a production fault model. Native execution has
not been performed by the host cross-build.
