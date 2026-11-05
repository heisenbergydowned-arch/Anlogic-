// SPDX-License-Identifier: GPL-2.0
/*
 * anlogic axi dma Controller Driver
 *
 * Copyright (c) 2024 anlogic Technologies Co., Ltd.
 */

#include <linux/bitops.h>
#include <linux/dmapool.h>
#include <linux/init.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/module.h>
#include <linux/of_address.h>
#include <linux/of_dma.h>
#include <linux/of_platform.h>
#include <linux/of_irq.h>
#include <linux/slab.h>
#include <linux/clk.h>
#include <linux/io-64-nonatomic-lo-hi.h>

#include "../dmaengine.h"

#include <linux/dma/anlogic_dma.h>

static void anlogic_axivdma_free_tx_descriptor(struct anlogic_dma_chan *chan,
				   struct anlogic_dma_tx_descriptor *desc)
{
	struct anlogic_vdma_tx_segment *segment, *next;

	if (!desc)
		return;

	list_for_each_entry_safe(segment, next, &desc->segments, node) {
		list_del(&segment->node);
		anlogic_vdma_free_tx_segment(chan, segment);
	}

	kfree(desc);
}

static void anlogic_dma_free_desc_list(struct anlogic_dma_chan *chan,
					struct list_head *list)
{
	struct anlogic_dma_tx_descriptor *desc, *next;

	list_for_each_entry_safe(desc, next, list, node) {
		list_del(&desc->node);
		anlogic_axivdma_free_tx_descriptor(chan, desc);
	}
}

static void anlogic_dma_free_descriptors(struct anlogic_dma_chan *chan)
{
	unsigned long flags;

	spin_lock_irqsave(&chan->lock, flags);

	anlogic_dma_free_desc_list(chan, &chan->pending_list);
	anlogic_dma_free_desc_list(chan, &chan->done_list);
	anlogic_dma_free_desc_list(chan, &chan->active_list);

	spin_unlock_irqrestore(&chan->lock, flags);
}

static void anlogic_axivdma_free_chan_resources(struct dma_chan *dchan)
{
	struct anlogic_dma_chan *chan = to_anlogic_chan(dchan);

	dev_dbg(chan->dev, "Free all channel resources.\n");

	anlogic_dma_free_descriptors(chan);

	dma_pool_destroy(chan->desc_pool);
	chan->desc_pool = NULL;
}

static int anlogic_axivdma_alloc_chan_resources(struct dma_chan *dchan)
{
	struct anlogic_dma_chan *chan = to_anlogic_chan(dchan);

	/* Has this channel already been allocated? */
	if (chan->desc_pool)
		return 0;

	/*
	 * We need the descriptor to be aligned to 64bytes
	 * for meeting Anlogic VDMA specification requirement.
	 */

	chan->desc_pool = dma_pool_create("anlogic_axivdma_desc_pool",
				chan->dev,
				sizeof(struct anlogic_vdma_tx_segment),
				__alignof__(struct anlogic_vdma_tx_segment),
				0);

	if (!chan->desc_pool) {
		dev_err(chan->dev,
			"unable to allocate channel %d descriptor pool\n",
			chan->id);
		return -ENOMEM;
	}

	dma_cookie_init(dchan);

	return 0;
}

static int anlogic_axivdma_terminate_all(struct dma_chan *dchan)
{
	struct anlogic_dma_chan *chan = to_anlogic_chan(dchan);
	u32 reg;
	int err;

	if (!chan->cyclic) {
		err = chan->stop_transfer(chan);
		if (err) {
			dev_err(chan->dev, "Cannot stop channel %p: %x\n",
				chan, dma_ctrl_read(chan,
				ANLOGIC_DMA_REG_DMASR));
			chan->err = true;
		}
	}

	anlogic_dma_chan_reset(chan);
	/* Remove and free all of the descriptors in the lists */
	chan->terminating = true;
	anlogic_dma_free_descriptors(chan);
	chan->idle = true;

	if (chan->cyclic) {
		reg = dma_ctrl_read(chan, ANLOGIC_DMA_REG_DMACR);
		reg &= ~ANLOGIC_DMA_CR_CYCLIC_BD_EN_MASK;
		dma_ctrl_write(chan, ANLOGIC_DMA_REG_DMACR, reg);
		chan->cyclic = false;
	}

	return 0;
}

static void anlogic_axivdma_synchronize(struct dma_chan *dchan)
{
	struct anlogic_dma_chan *chan = to_anlogic_chan(dchan);

	tasklet_kill(&chan->tasklet);
}

static enum dma_status anlogic_axivdma_tx_status(struct dma_chan *dchan,
					dma_cookie_t cookie,
					struct dma_tx_state *txstate)
{
	struct anlogic_dma_chan *chan = to_anlogic_chan(dchan);
	struct anlogic_dma_tx_descriptor *desc;
	enum dma_status ret;
	unsigned long flags;
	u32 residue = 0;

	ret = dma_cookie_status(dchan, cookie, txstate);
	if (ret == DMA_COMPLETE || !txstate)
		return ret;

	spin_lock_irqsave(&chan->lock, flags);
	if (!list_empty(&chan->active_list)) {
		desc = list_last_entry(&chan->active_list,
					   struct anlogic_dma_tx_descriptor, node);
	}
	spin_unlock_irqrestore(&chan->lock, flags);

	dma_set_residue(txstate, residue);

	return ret;
}

static void anlogic_axivdma_issue_pending(struct dma_chan *dchan)
{
	struct anlogic_dma_chan *chan = to_anlogic_chan(dchan);
	unsigned long flags;

	spin_lock_irqsave(&chan->lock, flags);
	chan->start_transfer(chan);
	spin_unlock_irqrestore(&chan->lock, flags);
}

static int anlogic_axivdma_device_config(struct dma_chan *dchan,
					struct dma_slave_config *config)
{
	return 0;
}

static struct anlogic_vdma_tx_segment *
anlogic_vdma_alloc_tx_segment(struct anlogic_dma_chan *chan)
{
	struct anlogic_vdma_tx_segment *segment;
	dma_addr_t phys;

	segment = dma_pool_zalloc(chan->desc_pool, GFP_ATOMIC, &phys);
	if (!segment)
		return NULL;

	segment->phys = phys;

	return segment;
}

static struct dma_async_tx_descriptor *
anlogic_axivdma_prep_interleaved(struct dma_chan *dchan,
				 struct dma_interleaved_template *xt,
				 unsigned long flags)
{
	struct anlogic_dma_chan *chan = to_anlogic_chan(dchan);
	struct anlogic_dma_tx_descriptor *desc;
	struct anlogic_vdma_tx_segment *segment;
	struct anlogic_vdma_desc_hw *hw;

	if (!is_slave_direction(xt->dir))
		return NULL;

	if (!xt->numf || !xt->sgl[0].size)
		return NULL;

	if (xt->frame_size != 1)
		return NULL;

	/* Allocate a transaction descriptor. */
	desc = anlogic_dma_alloc_tx_descriptor(chan);
	if (!desc)
		return NULL;

	dma_async_tx_descriptor_init(&desc->async_tx, &chan->common);
	desc->async_tx.tx_submit = anlogic_dma_tx_submit;
	async_tx_ack(&desc->async_tx);

	/* Allocate the link descriptor from DMA pool */
	segment = anlogic_vdma_alloc_tx_segment(chan);
	if (!segment)
		goto error;

	/* Fill in the hardware descriptor */
	hw = &segment->hw;
	hw->vsize = xt->numf;
	hw->hsize = xt->sgl[0].size;
	hw->stride = (xt->sgl[0].icg + xt->sgl[0].size) <<
			ANLOGIC_DMA_FRMDLY_STRIDE_STRIDE_SHIFT;
	hw->stride |= chan->config.frm_dly <<
			ANLOGIC_DMA_FRMDLY_STRIDE_FRMDLY_SHIFT;

	if (xt->dir != DMA_MEM_TO_DEV) {
		if (chan->ext_addr) {
			hw->buf_addr = lower_32_bits(xt->dst_start);
			hw->buf_addr_msb = upper_32_bits(xt->dst_start);
		} else {
			hw->buf_addr = xt->dst_start;
		}
	} else {
		if (chan->ext_addr) {
			hw->buf_addr = lower_32_bits(xt->src_start);
			hw->buf_addr_msb = upper_32_bits(xt->src_start);
		} else {
			hw->buf_addr = xt->src_start;
		}
	}

	/* Insert the segment into the descriptor segments list. */
	list_add_tail(&segment->node, &desc->segments);

	/* Link the last hardware descriptor with the first. */
	segment = list_first_entry(&desc->segments,
				   struct anlogic_vdma_tx_segment, node);
	desc->async_tx.phys = segment->phys;

	return &desc->async_tx;

error:
	anlogic_axivdma_free_tx_descriptor(chan, desc);
	return NULL;
}

static void anlogic_axivdma_complete_descriptor(struct anlogic_dma_chan *chan)
{
	struct anlogic_dma_tx_descriptor *desc, *next;

	/* This function was invoked with lock held */
	if (list_empty(&chan->active_list))
		return;

	list_for_each_entry_safe(desc, next, &chan->active_list, node) {
		desc->residue = 0;

		desc->err = chan->err;

		list_del(&desc->node);
		if (!desc->cyclic)
			dma_cookie_complete(&desc->async_tx);
		list_add_tail(&desc->node, &chan->done_list);
	}
}

static void anlogic_axivdma_append_desc_queue(struct anlogic_dma_chan *chan,
				  struct anlogic_dma_tx_descriptor *desc)
{
	struct anlogic_dma_tx_descriptor *tail_desc;
	struct anlogic_vdma_tx_segment *tail_segment;

	if (list_empty(&chan->pending_list))
		goto append;

	/*
	 * Add the hardware descriptor to the chain of hardware descriptors
	 * that already exists in memory.
	 */
	tail_desc = list_last_entry(&chan->pending_list,
					struct anlogic_dma_tx_descriptor, node);

	tail_segment = list_last_entry(&tail_desc->segments,
					struct anlogic_vdma_tx_segment,
					node);
	tail_segment->hw.next_desc = (u32)desc->async_tx.phys;

	/*
	 * Add the software descriptor and all children to the list
	 * of pending transactions
	 */
append:
	list_add_tail(&desc->node, &chan->pending_list);
	chan->desc_pendingcount++;
}

static void anlogic_axivdma_start_transfer(struct anlogic_dma_chan *chan)
{
	struct anlogic_vdma_config *config = &chan->config;
	struct anlogic_dma_tx_descriptor *desc;
	u32 reg, j;
	struct anlogic_vdma_tx_segment *segment, *last = NULL;
	int i = 0;

	/* This function was invoked with lock held */
	if (chan->err)
		return;

	if (!chan->idle)
		return;

	if (list_empty(&chan->pending_list))
		return;

	desc = list_first_entry(&chan->pending_list,
				struct anlogic_dma_tx_descriptor, node);

	/* Configure the hardware using info in the config structure */
	if (chan->has_vflip) {
		reg = dma_read(chan, ANLOGIC_VDMA_REG_ENABLE_VERTICAL_FLIP);
		reg &= ~ANLOGIC_VDMA_ENABLE_VERTICAL_FLIP;
		reg |= config->vflip_en;
		dma_write(chan, ANLOGIC_VDMA_REG_ENABLE_VERTICAL_FLIP,
			  reg);
	}

	reg = dma_ctrl_read(chan, ANLOGIC_DMA_REG_DMACR);

	if (config->frm_cnt_en)
		reg |= ANLOGIC_DMA_DMACR_FRAMECNT_EN;
	else
		reg &= ~ANLOGIC_DMA_DMACR_FRAMECNT_EN;

	/* If not parking, enable circular mode */
	if (config->park)
		reg &= ~ANLOGIC_DMA_DMACR_CIRC_EN;
	else
		reg |= ANLOGIC_DMA_DMACR_CIRC_EN;

	dma_ctrl_write(chan, ANLOGIC_DMA_REG_DMACR, reg);

	j = chan->desc_submitcount;
	reg = dma_read(chan, ANLOGIC_DMA_REG_PARK_PTR);
	if (chan->direction == DMA_MEM_TO_DEV) {
		reg &= ~ANLOGIC_DMA_PARK_PTR_RD_REF_MASK;
		reg |= j << ANLOGIC_DMA_PARK_PTR_RD_REF_SHIFT;
	} else {
		reg &= ~ANLOGIC_DMA_PARK_PTR_WR_REF_MASK;
		reg |= j << ANLOGIC_DMA_PARK_PTR_WR_REF_SHIFT;
	}
	dma_write(chan, ANLOGIC_DMA_REG_PARK_PTR, reg);

	/* Start the hardware */
	anlogic_dma_start(chan);

	if (chan->err)
		return;

	/* Start the transfer */
	if (chan->desc_submitcount < chan->num_frms)
		i = chan->desc_submitcount;

	list_for_each_entry(segment, &desc->segments, node) {
		if (chan->ext_addr)
			vdma_desc_write_64(chan,
				   ANLOGIC_VDMA_REG_START_ADDRESS_64(i++),
				   segment->hw.buf_addr,
				   segment->hw.buf_addr_msb);
		else
			vdma_desc_write(chan,
					ANLOGIC_VDMA_REG_START_ADDRESS(i++),
					segment->hw.buf_addr);

		last = segment;
	}

	if (!last)
		return;

	/* HW expects these parameters to be same for one transaction */
	vdma_desc_write(chan, ANLOGIC_DMA_REG_HSIZE, last->hw.hsize);
	vdma_desc_write(chan, ANLOGIC_DMA_REG_FRMDLY_STRIDE,
			last->hw.stride);
	vdma_desc_write(chan, ANLOGIC_DMA_REG_VSIZE, last->hw.vsize);

	chan->desc_submitcount++;
	chan->desc_pendingcount--;
	list_move_tail(&desc->node, &chan->active_list);
	if (chan->desc_submitcount == chan->num_frms)
		chan->desc_submitcount = 0;

	chan->idle = false;
}

static int anlogic_axivdma_stop_transfer(struct anlogic_dma_chan *chan)
{
	u32 val;

	dma_ctrl_clr(chan, ANLOGIC_DMA_REG_DMACR, ANLOGIC_DMA_DMACR_RUNSTOP);

	/* Wait for the hardware to halt */
	return anlogic_dma_poll_timeout(chan, ANLOGIC_DMA_REG_DMASR, val,
					   val & ANLOGIC_DMA_DMASR_HALTED, 0,
					   ANLOGIC_DMA_LOOP_COUNT);
}

int anlogic_vdma_channel_set_config(struct dma_chan *dchan,
					struct anlogic_vdma_config *cfg)
{
	struct anlogic_dma_chan *chan = to_anlogic_chan(dchan);
	u32 dmacr;

	if (cfg->reset)
		return anlogic_dma_chan_reset(chan);

	dmacr = dma_ctrl_read(chan, ANLOGIC_DMA_REG_DMACR);

	chan->config.frm_dly = cfg->frm_dly;
	chan->config.park = cfg->park;

	/* genlock settings */
	chan->config.gen_lock = cfg->gen_lock;
	chan->config.master = cfg->master;

	dmacr &= ~ANLOGIC_DMA_DMACR_GENLOCK_EN;
	if (cfg->gen_lock && chan->genlock) {
		dmacr |= ANLOGIC_DMA_DMACR_GENLOCK_EN;
		dmacr &= ~ANLOGIC_DMA_DMACR_MASTER_MASK;
		dmacr |= cfg->master << ANLOGIC_DMA_DMACR_MASTER_SHIFT;
	}

	chan->config.frm_cnt_en = cfg->frm_cnt_en;
	chan->config.vflip_en = cfg->vflip_en;

	if (cfg->park)
		chan->config.park_frm = cfg->park_frm;
	else
		chan->config.park_frm = -1;

	chan->config.coalesc = cfg->coalesc;
	chan->config.delay = cfg->delay;

	if (cfg->coalesc <= ANLOGIC_DMA_DMACR_FRAME_COUNT_MAX) {
		dmacr &= ~ANLOGIC_DMA_DMACR_FRAME_COUNT_MASK;
		dmacr |= cfg->coalesc << ANLOGIC_DMA_DMACR_FRAME_COUNT_SHIFT;
		chan->config.coalesc = cfg->coalesc;
	}

	if (cfg->delay <= ANLOGIC_DMA_DMACR_DELAY_MAX) {
		dmacr &= ~ANLOGIC_DMA_DMACR_DELAY_MASK;
		dmacr |= cfg->delay << ANLOGIC_DMA_DMACR_DELAY_SHIFT;
		chan->config.delay = cfg->delay;
	}

	/* FSync Source selection */
	dmacr &= ~ANLOGIC_DMA_DMACR_FSYNCSRC_MASK;
	dmacr |= cfg->ext_fsync << ANLOGIC_DMA_DMACR_FSYNCSRC_SHIFT;

	dma_ctrl_write(chan, ANLOGIC_DMA_REG_DMACR, dmacr);

	return 0;
}
EXPORT_SYMBOL(anlogic_vdma_channel_set_config);

struct anlogic_dma_init axivdma_init = {
	.dma_ops = {
		.device_alloc_chan_resources = anlogic_axivdma_alloc_chan_resources,
		.device_free_chan_resources = anlogic_axivdma_free_chan_resources,
		.device_terminate_all = anlogic_axivdma_terminate_all,
		.device_synchronize = anlogic_axivdma_synchronize,
		.device_tx_status = anlogic_axivdma_tx_status,
		.device_issue_pending = anlogic_axivdma_issue_pending,
		.device_config = anlogic_axivdma_device_config,
		.device_prep_interleaved_dma = anlogic_axivdma_prep_interleaved
	},

	.desc_ops = {
		.complete_descriptor = anlogic_axivdma_complete_descriptor,
		.append_desc_queue = anlogic_axivdma_append_desc_queue,
		.dma_free_tx_descriptor = anlogic_axivdma_free_tx_descriptor,
	},

	.start_transfer = anlogic_axivdma_start_transfer,
	.stop_transfer  = anlogic_axivdma_stop_transfer,
};

MODULE_AUTHOR("anlogic, Inc.");
MODULE_DESCRIPTION("anlogic axi vdma Controller Driver");
MODULE_LICENSE("GPL");
