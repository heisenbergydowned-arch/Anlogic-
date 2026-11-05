#include <armnn/ArmNN.hpp>
#include <armnnOnnxParser/IOnnxParser.hpp>
#include <cstdio>
#include <stdexcept>
int main(int argc,char**argv) {
    if(argc!=2)return 2;
    try {
        std::fprintf(stderr,"CPU_ONLY_PARSER_CREATE\n");
        auto parser=armnnOnnxParser::IOnnxParser::Create();
        std::fprintf(stderr,"CPU_ONLY_ONNX_PARSE\n");
        auto graph=parser->CreateNetworkFromBinaryFile(argv[1]);
        if(!graph)throw std::runtime_error("Null graph");
        auto inputs=parser->GetInputTensorNames(),outputs=parser->GetOutputTensorNames();
        if(inputs.size()!=1||outputs.size()!=1)throw std::runtime_error("Wrong bindings");
        auto in=parser->GetNetworkInputBindingInfo(inputs[0]).second;
        auto out=parser->GetNetworkOutputBindingInfo(outputs[0]).second;
        if(in.GetNumDimensions()!=2||out.GetNumDimensions()!=2)throw std::runtime_error("Wrong rank");
        std::printf("PASS_SDK_PARSE_ONLY input=%ux%u output=%ux%u input_scale=%.10g output_scale=%.10g npu_executed=false\n",in.GetShape()[0],in.GetShape()[1],out.GetShape()[0],out.GetShape()[1],in.GetQuantizationScale(),out.GetQuantizationScale());
        return 0;
    } catch(const std::exception& e) { std::fprintf(stderr,"%s\n",e.what());return 1; }
}
