#include <armnn/ArmNN.hpp>
#include <armnnOnnxParser/IOnnxParser.hpp>
#include <armnnALUtils/cma_mem_init.hpp>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <locale>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>

namespace {
thread_local std::string error_text;
void phase(const char* value) { std::fprintf(stderr, "NORMAL_NATIVE_INIT %s\n", value); std::fflush(stderr); }
struct Engine {
    armnn::IRuntimePtr runtime{nullptr, +[](armnn::IRuntime*){}};
    armnn::NetworkId network=0;
    armnn::BindingPointInfo input, output;
    cma_buffer_t input_buffer, output_buffer;
    bool cma=false, loaded=false, poisoned=false;
    std::string metadata;
    std::string optimized_dot;

    explicit Engine(const char* path) {
        phase("cma_begin");
        if (!path || cma_mem_init()!=0) throw std::runtime_error("CMA init/model path failure");
        cma=true;
        phase("cma_ready");
        try {
            phase("runtime_create");
            runtime=armnn::IRuntime::Create(armnn::IRuntime::CreationOptions{});
            auto parser=armnnOnnxParser::IOnnxParser::Create();
            phase("onnx_parse");
            auto graph=parser->CreateNetworkFromBinaryFile(path);
            phase("onnx_parsed");
            const auto inputs=parser->GetInputTensorNames(), outputs=parser->GetOutputTensorNames();
            if (inputs.size()!=1 || outputs.size()!=1) throw std::runtime_error("One input/output required");
            input=parser->GetNetworkInputBindingInfo(inputs[0]);
            output=parser->GetNetworkOutputBindingInfo(outputs[0]);
            check_tensor(input.second,39);
            check_tensor(output.second,39);
            armnn::OptimizerOptionsOpaque optimization;
            optimization.SetImportEnabled(true);
            optimization.SetExportEnabled(true);
            phase("alnpu_optimize");
            auto optimized=armnn::Optimize(*graph,{armnn::BackendId("Alnpu")},runtime->GetDeviceSpec(),optimization);
            if (!optimized) throw std::runtime_error("Alnpu-only graph optimization failed; no CPU fallback");
            phase("alnpu_optimized");
            std::ostringstream graph_stream;
            if (optimized->SerializeToDot(graph_stream)!=armnn::Status::Success)
                throw std::runtime_error("Alnpu optimized graph audit export failed");
            optimized_dot=graph_stream.str();
            std::string detail;
            armnn::INetworkProperties properties(false,armnn::MemorySource::Malloc,armnn::MemorySource::Malloc);
            phase("network_load");
            if (runtime->LoadNetwork(network,std::move(optimized),detail,properties)!=armnn::Status::Success)
                throw std::runtime_error("Alnpu LoadNetwork: "+detail);
            loaded=true;
            phase("network_loaded");
            phase("io_allocate");
            input_buffer=cma_buffer_t(39);
            output_buffer=cma_buffer_t(39);
            if (cma_mem_alloc(&input_buffer)!=0 || !input_buffer.virt_addr ||
                cma_mem_alloc(&output_buffer)!=0 || !output_buffer.virt_addr)
                throw std::runtime_error("CMA allocation failed");
            phase("io_ready");
            input.second.SetConstant(true);
            std::ostringstream text;
            text.imbue(std::locale::classic());
            text << std::setprecision(10)
                 << "{\"abi_version\":1,\"input_shape\":[1,39],\"output_shape\":[1,39],"
                 << "\"input_dtype\":\"uint8\",\"output_dtype\":\"uint8\",\"requested_backends\":[\"Alnpu\"],"
                 << "\"backend_audit_schema\":\"cabinet-alnpu-graph-v1\","
                 << "\"execution_model\":\"ALNPU_NORMAL_RECONSTRUCTION_39\","
                 << "\"postprocess\":\"PS_RECONSTRUCTION_RESIDUAL_NOT_CLASSIFICATION\","
                 << "\"hardware_profile\":\"DR1M90_NORMAL_AE39_V1\","
                 << "\"compatible_pl_build_ids\":[539365623],"
                 << "\"reconstruction_scale\":" << output.second.GetQuantizationScale()
                 << ",\"reconstruction_zero_point\":" << output.second.GetQuantizationOffset() << ","
                 << "\"input_scale\":" << input.second.GetQuantizationScale()
                 << ",\"input_zero_point\":" << input.second.GetQuantizationOffset()
                 << ",\"output_scale\":" << output.second.GetQuantizationScale()
                 << ",\"output_zero_point\":" << output.second.GetQuantizationOffset() << "}";
            metadata=text.str();
            phase("ready");
        } catch (...) { cleanup(); throw; }
    }

    static void check_tensor(const armnn::TensorInfo& tensor,unsigned elements) {
        if (tensor.GetNumDimensions()!=2 || tensor.GetShape()[0]!=1 || tensor.GetShape()[1]!=elements ||
            tensor.GetDataType()!=armnn::DataType::QAsymmU8 || tensor.HasPerAxisQuantization())
            throw std::runtime_error("Exact batch-one per-tensor UINT8 shape required");
        if (!std::isfinite(tensor.GetQuantizationScale()) || tensor.GetQuantizationScale()<=0 ||
            tensor.GetQuantizationOffset()<0 || tensor.GetQuantizationOffset()>255)
            throw std::runtime_error("Invalid UINT8 quantization metadata");
    }

    void cleanup() {
        if (loaded && runtime) { runtime->UnloadNetwork(network); loaded=false; }
        runtime.reset();
        if (input_buffer.phys_addr) cma_mem_free(&input_buffer);
        if (output_buffer.phys_addr) cma_mem_free(&output_buffer);
        if (cma) { cma_mem_deinit(); cma=false; }
    }

    ~Engine() { cleanup(); }

    void run(const uint8_t* values,uint8_t* probabilities) {
        if (!values || !probabilities || poisoned) throw std::runtime_error("Null input or latched native fault");
        try {
            std::memcpy(input_buffer.virt_addr,values,39);
            if (cma_mem_sync_for_device(input_buffer.phys_addr,input_buffer.size)!=0)
                throw std::runtime_error("CMA input sync failed");
            armnn::InputTensors inputs{{input.first,armnn::ConstTensor(input.second,input_buffer.virt_addr)}};
            armnn::OutputTensors outputs{{output.first,armnn::Tensor(output.second,output_buffer.virt_addr)}};
            if (runtime->EnqueueWorkload(network,inputs,outputs)!=armnn::Status::Success)
                throw std::runtime_error("Alnpu inference failed");
            if (cma_mem_sync_for_cpu(output_buffer.phys_addr,output_buffer.size)!=0)
                throw std::runtime_error("CMA output sync failed");
            std::memcpy(probabilities, output_buffer.virt_addr, 39);
        } catch (...) { poisoned=true; throw; }
    }
};
}

extern "C" {
const char* edge_normal_profile() {
    return "{\"hardware_profile\":\"DR1M90_NORMAL_AE39_V1\",\"compatible_pl_build_ids\":[539365623]}";
}
const char* edge_normal_error() { return error_text.c_str(); }
void* edge_normal_open(const char* path) {
    try { return new Engine(path); }
    catch (const std::exception& error) { error_text=error.what(); return nullptr; }
    catch (...) { error_text="Unknown native initialization failure"; return nullptr; }
}
const char* edge_normal_info(void* handle) {
    if (!handle) { error_text="Null native handle"; return nullptr; }
    return static_cast<Engine*>(handle)->metadata.c_str();
}
const char* edge_normal_graph_dot(void* handle) {
    if (!handle) { error_text="Null native handle"; return nullptr; }
    return static_cast<Engine*>(handle)->optimized_dot.c_str();
}
int edge_normal_run_u8(void* handle,const uint8_t* values,uint8_t* probabilities) {
    try {
        if (!handle) throw std::runtime_error("Null native handle");
        static_cast<Engine*>(handle)->run(values,probabilities);
        return 0;
    } catch (const std::exception& error) { error_text=error.what(); return -1; }
    catch (...) { error_text="Unknown native execution failure"; return -1; }
}
int edge_normal_close(void* handle) {
    auto* engine=static_cast<Engine*>(handle);
    if (engine && engine->poisoned) { error_text="Native fault retained; driver recovery required"; return -1; }
    delete engine;
    return 0;
}
}
