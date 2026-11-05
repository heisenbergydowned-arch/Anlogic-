/****************************************************************
 * Copyright (c) 2023 Anlogic, Inc.  All rights reserved.
 * SPDX-License-Identifier: MIT
 ****************************************************************/

#pragma once
#include <stdint.h>
#include <string>
struct cma_buffer_t {
    uint32_t size;             //
    uint32_t flags;            // cache flags 0:cache_shared,1:writecombine,2:nocached
    uint64_t phys_addr = 0;    //
    void *base = nullptr;      /* kernel logical address in use kernel */
    void *virt_addr = nullptr; /* virtual user space address */

    cma_buffer_t(uint32_t size_, uint32_t flags_);
    cma_buffer_t(uint32_t size_);
    cma_buffer_t();

    // 执行memcpy并执行sync_for_device
    void mem_write(void *src, size_t len);

    std::string dump_str();
};