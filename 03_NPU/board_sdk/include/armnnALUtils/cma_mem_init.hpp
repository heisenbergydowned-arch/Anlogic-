/****************************************************************
 * Copyright (c) 2023 Anlogic, Inc.  All rights reserved.
 * SPDX-License-Identifier: MIT
 ****************************************************************/

#ifndef __NPU_RUNTIME_CMA_MEM_INIT_H__
#define __NPU_RUNTIME_CMA_MEM_INIT_H__

#include "armnn/MemorySources.hpp"
#include "armnn/Types.hpp"
#include "armnn/utility/Assert.hpp"
#include "armnn/utility/IgnoreUnused.hpp"
#include "cma_mem.hpp"
#include <cstddef>
#include <cstdint>
int cma_mem_init();

int cma_mem_deinit();

bool cma_mem_is_init();

int cma_mem_sync_for_cpu(uint64_t phy_addr, size_t len);

int cma_mem_sync_for_device(uint64_t phy_addr, size_t len);

void cma_print_used();

// 需要设置好bf->size 和bf->flag后调用
int cma_mem_alloc(cma_buffer_t *bf);

int cma_mem_free(cma_buffer_t *bf);

// 返回使用内存大小(Byte)
size_t cma_mem_count();

/**
 * @brief 查询虚拟地址对应的物理地址
 *
 * @param dst 结果的存储位置
 * @param virt_addr 内存块的首地址到结束地址均可
 * @return true 找到
 * @return false 没找到
 */
bool cma_mem_search_buffer(cma_buffer_t &dst, void *virt_addr);

/**
 * @brief 查询虚拟地址对应的物理地址
 *
 * @param dst 结果的存储位置
 * @param virt_addr 内存块的首地址到结束地址均可
 * @return true 找到
 * @return false 没找到
 */
bool cma_mem_search_buffer(uint64_t &phy_addr, void *virt_addr);

/**
 * @brief 注册非本模块管理的cma内存，这有助于import tensor而不是拷贝。内存块需要支持sync_device sync_cpu
 * 
 * @param phy_addr 
 * @param virt_addr 
 * @param block_size 
 */
void cma_mem_search_register_block(uint64_t phy_addr, void* virt_addr, size_t block_size);

/*
usage :

Typical code for Custom Allocator looks like, When Create ArmNN runtime: 
    ....
    armnn::IRuntime::CreationOptions rt_options; 
    rt_options.m_CustomAllocatorMap["CpuRef"] = std::shared_ptr<armnn::ICustomAllocator>(new armnn::CmaAllocator);
    pRunPtr = std::make_shared<armnn::IRuntimePtr>(armnn::IRuntime::Create(rt_options));
    ....
*/

#include <armnn/backends/ICustomAllocator.hpp>
namespace armnn
{
class CmaAllocator : public ICustomAllocator
{
public:
    class bad_cmaAllocator : public std::bad_alloc
    {
    public:
        const char* what() const throw() override
        {
            return "cma alloc failed";
        }
    };
    class bad_cmaFree : public std::bad_alloc
    {
    public:
        const char* what() const throw() override
        {
            return "cma free failed";
        }
    };

    void* allocate(size_t size, size_t alignment) override
    {
        ARMNN_ASSERT(alignment <= 4096);
        IgnoreUnused(alignment);
        cma_buffer_t bf(size);
        cma_mem_alloc(&bf);
        if (bf.phys_addr == 0)
            throw bad_cmaAllocator();
        return bf.virt_addr;
    }

    void free(void* ptr) override
    {
        cma_buffer_t bf;
        if (cma_mem_search_buffer(bf, ptr))
        {
            cma_mem_free(&bf);
        }
        else
        {
            throw bad_cmaFree();
        }
    }

    /**  Used to specify what type of memory is being allocated by this allocator.
     *  Supported types are:
     *       MemorySource::Malloc
     *       MemorySource::DmaBuf
     *       MemorySource::DmaBufProtected
     */
    armnn::MemorySource GetMemorySourceType() override
    {
        return static_cast<armnn::MemorySource>(armnn::MemorySourceFlags(armnn::MemorySource::Malloc) |
                                                armnn::MemorySourceFlags(armnn::MemorySource::DmaBuf));
    }

    /** Interface that may be implemented to allow retrieval of Memory Region
     *  from allocated buffer at a certain offset
     */
    void* GetMemoryRegionAtOffset(void* buffer, size_t offset, size_t alignment = 0) override
    {
        IgnoreUnused(alignment);
        return (char*)buffer + offset;
    }
};
}    // namespace armnn

#endif