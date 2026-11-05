#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cfenv>
#include <cstdint>
#include <stdexcept>

namespace cabinet {
inline void softmax_u8(const uint8_t* logits, float scale, int zero, uint8_t* output) {
    if (!logits || !output || !std::isfinite(scale) || scale <= 0 || zero < 0 || zero > 255)
        throw std::runtime_error("Invalid PS Softmax input or quantization");
    if (std::fegetround() != FE_TONEAREST) throw std::runtime_error("PS Softmax requires round-to-nearest FP32 arithmetic");
    std::array<float, 5> values{};
    for (unsigned index = 0; index < values.size(); ++index) {
        values[index] = static_cast<float>(static_cast<int>(logits[index]) - zero) * scale;
        if (!std::isfinite(values[index])) throw std::runtime_error("PS Softmax logit overflow");
    }
    const float maximum = *std::max_element(values.begin(), values.end());
    float total = 0;
    for (float& value : values) {
        value = std::exp(value - maximum);
        total += value;
    }
    if (!std::isfinite(total) || total <= 0) throw std::runtime_error("Invalid PS Softmax normalization");
    constexpr float probability_scale = 1.0f / 255.0f;
    for (unsigned index = 0; index < values.size(); ++index) {
        const float scaled = (values[index] / total) / probability_scale;
        const float lower = std::floor(scaled);
        const float fraction = scaled - lower;
        int rounded = static_cast<int>(lower);
        if (fraction > 0.5f || (fraction == 0.5f && rounded % 2 != 0)) ++rounded;
        if (rounded < 0 || rounded > 255) throw std::runtime_error("PS Softmax probability outside UINT8");
        output[index] = static_cast<uint8_t>(rounded);
    }
}
}
