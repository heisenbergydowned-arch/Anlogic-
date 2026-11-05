// Board-SDK adapter: ArmNN 32.1 / Alnpu backend only. No CpuAcc/CpuRef fallback.
// Public C ABI avoids imposing the SDK's C++ ABI on Python.
#include <armnn/ArmNN.hpp>
#include <armnnOnnxParser/IOnnxParser.hpp>
#include <armnnALUtils/cma_mem_init.hpp>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
thread_local std::string error_text;
struct Engine {
    armnn::IRuntimePtr runtime{nullptr,+[](armnn::IRuntime*){}};
    armnn::NetworkId network=0;
    armnn::BindingPointInfo input,output;
    cma_buffer_t in_buffer,out_buffer;
    bool cma=false,loaded=false;
    Engine(const char* path) {
        if(cma_mem_init()!=0)throw std::runtime_error("CMA init failed; install board cma_mem driver");
        cma=true;
        try {
            armnn::IRuntime::CreationOptions options;
            runtime=armnn::IRuntime::Create(options);
            auto parser=armnnOnnxParser::IOnnxParser::Create();
            auto graph=parser->CreateNetworkFromBinaryFile(path);
            const auto ins=parser->GetInputTensorNames(),outs=parser->GetOutputTensorNames();
            if(ins.size()!=1||outs.size()!=1)throw std::runtime_error("One input and one output are required");
            input=parser->GetNetworkInputBindingInfo(ins[0]);output=parser->GetNetworkOutputBindingInfo(outs[0]);
            if(input.second.GetNumElements()!=39||output.second.GetNumElements()!=5)
                throw std::runtime_error("Model must accept 39 features and return five probabilities");
            check_type(input.second);check_type(output.second);
            // Unsupported FC/scaler/softmax must fail here, never run on CPU.
            armnn::OptimizerOptionsOpaque opt;
            opt.SetImportEnabled(true);opt.SetExportEnabled(true);
            auto optimized=armnn::Optimize(*graph,{armnn::BackendId("Alnpu")},runtime->GetDeviceSpec(),opt);
            if(!optimized)throw std::runtime_error("Alnpu-only graph optimization failed");
            std::string detail;
            armnn::INetworkProperties properties(false,armnn::MemorySource::Malloc,armnn::MemorySource::Malloc);
            if(runtime->LoadNetwork(network,std::move(optimized),detail,properties)!=armnn::Status::Success)
                throw std::runtime_error("Alnpu LoadNetwork: "+detail);
            loaded=true;
            in_buffer=cma_buffer_t(input.second.GetNumBytes());out_buffer=cma_buffer_t(output.second.GetNumBytes());
            if(cma_mem_alloc(&in_buffer)!=0||!in_buffer.virt_addr||cma_mem_alloc(&out_buffer)!=0||!out_buffer.virt_addr)
                throw std::runtime_error("CMA tensor allocation failed");
            input.second.SetConstant(true);
        } catch(...) {cleanup();throw;}
    }
    static void check_type(const armnn::TensorInfo& info) {
        auto type=info.GetDataType();
        if(type!=armnn::DataType::Float32 && type!=armnn::DataType::QAsymmU8 &&
           type!=armnn::DataType::QAsymmS8 && type!=armnn::DataType::QSymmS8)
            throw std::runtime_error("Only FP32 and per-tensor 8-bit tensors are supported");
        if(type!=armnn::DataType::Float32 && (!std::isfinite(info.GetQuantizationScale())||info.GetQuantizationScale()<=0))
            throw std::runtime_error("Invalid quantization scale");
        if(info.HasPerAxisQuantization())throw std::runtime_error("Per-axis input/output quantization is unsupported");
    }
    void cleanup() {
        if(loaded&&runtime){runtime->UnloadNetwork(network);loaded=false;}
        runtime.reset();
        if(in_buffer.phys_addr)cma_mem_free(&in_buffer);
        if(out_buffer.phys_addr)cma_mem_free(&out_buffer);
        if(cma){cma_mem_deinit();cma=false;}
    }
    ~Engine(){cleanup();}
    void run(const float* x,float* y) {
        const auto type=input.second.GetDataType();
        if(type==armnn::DataType::Float32)std::memcpy(in_buffer.virt_addr,x,39*sizeof(float));
        else for(unsigned i=0;i<39;i++) {
            double q=std::round(x[i]/input.second.GetQuantizationScale())+input.second.GetQuantizationOffset();
            const bool u=type==armnn::DataType::QAsymmU8;
            if(!std::isfinite(q)||q<(u?0:-128)||q>(u?255:127))throw std::runtime_error("Input outside quantized model range");
            static_cast<unsigned char*>(in_buffer.virt_addr)[i]=static_cast<unsigned char>(static_cast<int>(q));
        }
        cma_mem_sync_for_device(in_buffer.phys_addr,in_buffer.size);
        armnn::InputTensors inputs{{input.first,armnn::ConstTensor(input.second,in_buffer.virt_addr)}};
        armnn::OutputTensors outputs{{output.first,armnn::Tensor(output.second,out_buffer.virt_addr)}};
        if(runtime->EnqueueWorkload(network,inputs,outputs)!=armnn::Status::Success)throw std::runtime_error("Alnpu inference failed");
        cma_mem_sync_for_cpu(out_buffer.phys_addr,out_buffer.size);
        const auto ot=output.second.GetDataType();
        if(ot==armnn::DataType::Float32)std::memcpy(y,out_buffer.virt_addr,5*sizeof(float));
        else for(unsigned i=0;i<5;i++) {
            const int q=ot==armnn::DataType::QAsymmU8?static_cast<unsigned char*>(out_buffer.virt_addr)[i]:static_cast<signed char*>(out_buffer.virt_addr)[i];
            y[i]=(q-output.second.GetQuantizationOffset())*output.second.GetQuantizationScale();
        }
    }
};
}
extern "C" {
const char* edge_npu_error(){return error_text.c_str();}
void* edge_npu_open(const char* path){try{return new Engine(path);}catch(const std::exception& e){error_text=e.what();return nullptr;}}
int edge_npu_run(void* engine,const float* x,float* y){try{static_cast<Engine*>(engine)->run(x,y);return 0;}catch(const std::exception& e){error_text=e.what();return -1;}}
void edge_npu_close(void* engine){delete static_cast<Engine*>(engine);}
}
