// Offline verification only. Alnpu graphs are NEVER loaded or executed here.
#include <armnn/ArmNN.hpp>
#include <armnnOnnxParser/IOnnxParser.hpp>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    if (argc != 5) return 2;
    try {
        const std::string mode(argv[1]);
        if (mode != "graph-only" && mode != "cpu-ref" && mode != "al-ref") throw std::runtime_error("Invalid offline mode");
        std::fprintf(stderr, "LOCAL_VM_SDK runtime_create\n");
        auto runtime = armnn::IRuntime::Create(armnn::IRuntime::CreationOptions{});
        auto parser = armnnOnnxParser::IOnnxParser::Create();
        auto graph = parser->CreateNetworkFromBinaryFile(argv[2]);
        const auto in = parser->GetNetworkInputBindingInfo(parser->GetInputTensorNames().at(0));
        const auto out = parser->GetNetworkOutputBindingInfo(parser->GetOutputTensorNames().at(0));
        if (in.second.GetNumElements() != 39 || out.second.GetNumElements() != 39 ||
            in.second.GetDataType() != armnn::DataType::QAsymmU8 ||
            out.second.GetDataType() != armnn::DataType::QAsymmU8)
            throw std::runtime_error("Expected UINT8 39 to 39");
        armnn::OptimizerOptionsOpaque options;
        if (mode == "graph-only") { options.SetImportEnabled(true); options.SetExportEnabled(true); }
        const char* backend = mode == "graph-only" ? "Alnpu" : mode == "al-ref" ? "ALRef" : "CpuRef";
        std::fprintf(stderr, "LOCAL_VM_SDK optimize %s\n", backend);
        auto optimized = armnn::Optimize(*graph, {armnn::BackendId(backend)}, runtime->GetDeviceSpec(), options);
        if (!optimized) throw std::runtime_error("Offline optimization failed");
        std::ofstream dot(std::string(argv[4]) + ".dot");
        if (optimized->SerializeToDot(dot) != armnn::Status::Success) throw std::runtime_error("Graph export failed");
        dot.close();
        if (mode == "graph-only") {
            std::puts("PASS_ALNPU_GRAPH_ONLY no_network_load=true npu_executed=false");
            return 0;
        }
        armnn::NetworkId id = 0;
        std::string detail;
        if (runtime->LoadNetwork(id, std::move(optimized), detail) != armnn::Status::Success)
            throw std::runtime_error("CPU reference load failed: " + detail);
        std::ifstream input(argv[3], std::ios::binary);
        std::ofstream output(argv[4], std::ios::binary);
        if (!input || !output) throw std::runtime_error("Cannot open vectors");
        auto info = in.second;
        info.SetConstant(true);
        uint8_t x[39], y[39];
        unsigned count = 0;
        while (input.read(reinterpret_cast<char*>(x), 39)) {
            if (runtime->EnqueueWorkload(id, {{in.first, armnn::ConstTensor(info, x)}},
                                        {{out.first, armnn::Tensor(out.second, y)}}) != armnn::Status::Success)
                throw std::runtime_error("CPU reference inference failed");
            output.write(reinterpret_cast<const char*>(y), 39);
            ++count;
        }
        if (input.gcount() != 0) throw std::runtime_error("Partial input vector");
        if (runtime->UnloadNetwork(id) != armnn::Status::Success) throw std::runtime_error("Unload failed");
        std::printf("PASS_LOCAL_REFERENCE_ONLY backend=%s vectors=%u npu_executed=false\n", backend, count);
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
}
