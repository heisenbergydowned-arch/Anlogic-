/****************************************************************
 * Copyright (c) 2023 Anlogic, Inc.  All rights reserved.
 * SPDX-License-Identifier: MIT
 ****************************************************************/

#pragma once
#include "armnn/Tensor.hpp"
#include <cstdint>
#include <functional>
#include <vector>
#include <unordered_map>

struct DetectObject
{
    float prob;
    int16_t x;    //center of box in axis x
    int16_t y;    //center of box in axis y
    int16_t w;
    int16_t h;
    int16_t label;
};

typedef struct npu_input_quant_param {
    
    /* for input quant */
    int8_t r_mean_rshift;
    int16_t r_mean_param;
    int8_t g_mean_rshift;
    int16_t g_mean_param;
    int8_t b_mean_rshift;
    int16_t b_mean_param;
    int8_t r_quant_rshift;
    int16_t r_quant_param;
    int8_t g_quant_rshift;
    int16_t g_quant_param;
    int8_t b_quant_rshift;
    int16_t b_quant_param;
    int32_t input_zero_point;
    uint32_t quant_type = 0;    // 0 for uint8,others int8
} npu_input_quant_param_t;

std::function<std::vector<DetectObject>(const armnn::OutputTensors& outputTensors)>
    AlnpuYoloPostProcessWorkloadGet(const armnn::OutputTensors& outputTensors,
                                    uint32_t Width,
                                    uint32_t Height,
                                    std::unordered_map<int, std::vector<int>>& stride_anchor_map,
                                    int class_num,
                                    float prob_threshold = 0.25f,
                                    float nms_threshold = 0.45f);

std::function<std::vector<DetectObject>(const armnn::OutputTensors& outputTensors)>
    AlnpuYolov8PostProcessWorkloadGet(const armnn::OutputTensors& outputTensors,
                                    uint32_t Width,
                                    uint32_t Height,
                                    int class_num,
                                    float prob_threshold = 0.45f,
                                    float nms_threshold = 0.7f);

static inline std::vector<DetectObject>
    AlnpuYoloPostProcess(const armnn::OutputTensors& outputTensors,
                         uint32_t Width,
                         uint32_t Height,
                         std::unordered_map<int, std::vector<int>>& stride_anchor_map,
                         int class_num,
                         float prob_threshold = 0.25f,
                         float nms_threshold = 0.45f)
{
    return AlnpuYoloPostProcessWorkloadGet(outputTensors, Width, Height, stride_anchor_map, class_num, prob_threshold,
                                           nms_threshold)(outputTensors);
}

static inline std::vector<DetectObject>
    AlnpuYolov8PostProcess(const armnn::OutputTensors& outputTensors,
                         uint32_t Width,
                         uint32_t Height,
                         int class_num,
                         float prob_threshold = 0.45f,
                         float nms_threshold = 0.7f)
{
    return AlnpuYolov8PostProcessWorkloadGet(outputTensors, Width, Height, class_num, prob_threshold,
                                           nms_threshold)(outputTensors);
}

std::function<void(const armnn::ConstTensor& inputTensor,
                   const armnn::ConstTensor& outputTensor,
                   const npu_input_quant_param_t& in_quant_param)>
    AlnpuResizePreProcessWorkloadGet(const armnn::ConstTensor& inputTensor,
                                     const armnn::ConstTensor& outputTensor,
                                     const npu_input_quant_param_t& in_quant_param);

std::function<void(const armnn::ConstTensor& inputTensor,
                   const armnn::ConstTensor& outputTensor,
                   const npu_input_quant_param_t& in_quant_param)>
    AlnpuResizePreProcessWorkloadGetLetterbox(const armnn::ConstTensor& inputTensor,
                                     const armnn::ConstTensor& outputTensor,
                                     const npu_input_quant_param_t& in_quant_param,
                                     int (&histogram)[256]);