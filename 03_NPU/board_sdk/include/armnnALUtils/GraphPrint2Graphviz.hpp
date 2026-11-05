/****************************************************************
 * Copyright (c) 2023 Anlogic, Inc.  All rights reserved.
 * SPDX-License-Identifier: MIT
 ****************************************************************/

#include "armnn/INetwork.hpp"
#include "armnn/IRuntime.hpp"
#include <string>
namespace armnn
{
void GraphPrint2Graphviz(const armnn::INetwork& inNetwork, const std::string& dot);
void GraphPrint2Graphviz(const armnn::IOptimizedNetwork& inNetwork, const std::string& dot);
void GraphPrint2Graphviz(const armnn::IRuntime& inRuntime,
                         armnn::NetworkId networkId,
                         const std::string& dot,
                         bool printTensorAddr = false);

}    // namespace armnn