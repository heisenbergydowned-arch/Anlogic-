//
// Copyright © 2017 Arm Ltd. All rights reserved.
// SPDX-License-Identifier: MIT
//
#pragma once

#include "TensorFwd.hpp"
#include "Exceptions.hpp"

namespace armnn
{

struct LstmOnnxInputParams
{
    LstmOnnxInputParams()
        : m_W(nullptr)
        , m_R(nullptr)
        , m_B(nullptr)
        , m_SequenceLens(nullptr)
        , m_InitialH(nullptr)
        , m_InitialC(nullptr)
        , m_P(nullptr)
    {
    }

    const ConstTensor* m_W;
    const ConstTensor* m_R;
    const ConstTensor* m_B;
    const ConstTensor* m_SequenceLens;
    const ConstTensor* m_InitialH;
    const ConstTensor* m_InitialC;
    const ConstTensor* m_P;
};

struct LstmOnnxInputParamsInfo
{
    LstmOnnxInputParamsInfo()
            : m_W(nullptr)
            , m_R(nullptr)
            , m_B(nullptr)
            , m_SequenceLens(nullptr)
            , m_InitialH(nullptr)
            , m_InitialC(nullptr)
            , m_P(nullptr)
    {
    }
    const TensorInfo* m_W;
    const TensorInfo* m_R;
    const TensorInfo* m_B;
    const TensorInfo* m_SequenceLens;
    const TensorInfo* m_InitialH;
    const TensorInfo* m_InitialC;
    const TensorInfo* m_P;

    const TensorInfo& Deref(const TensorInfo* tensorInfo) const
    {
        if (tensorInfo != nullptr)
        {
            const TensorInfo &temp = *tensorInfo;
            return temp;
        }
        throw InvalidArgumentException("Can't dereference a null pointer");
    }

    const TensorInfo& GetW() const
    {
        return Deref(m_W);
    }
    const TensorInfo& GetR() const
    {
        return Deref(m_R);
    }
    const TensorInfo& GetB() const
    {
        return Deref(m_B);
    }
    const TensorInfo& GetSequenceLens() const
    {
        return Deref(m_SequenceLens);
    }
    const TensorInfo& GetInitialH() const
    {
        return Deref(m_InitialH);
    }
    const TensorInfo& GetInitialC() const
    {
        return Deref(m_InitialC);
    }
    const TensorInfo& GetP() const
    {
        return Deref(m_P);
    }
};

} // namespace armnn

