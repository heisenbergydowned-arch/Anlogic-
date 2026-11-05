// SPDX-License-Identifier: GPL-2.0
/*
 * Anlogic framebuffer Driver
 *
 * Copyright (c) 2025 anlogic Technologies Co., Ltd.
 */

#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/fb.h>
#include <linux/of_dma.h>
#include "anlogic-vtc.h"
#include <linux/dma/anlogic_dma.h>
#include <video/videomode.h>
#include <linux/delay.h>
#include <video/of_videomode.h>
#include <video/of_display_timing.h>

struct vdmafb_dev {
	struct fb_info *info;
	struct platform_device *pdev;
	struct dma_chan *vdma;
	void __iomem *vtc_base;
};

static int vdmafb_vdma_init(struct vdmafb_dev *fbdev)
{
	struct device *dev = &fbdev->pdev->dev;
	struct fb_info *info = fbdev->info;
	struct dma_interleaved_template *xt;
	struct dma_async_tx_descriptor *tx_desc;
	struct anlogic_vdma_config config = {0};
	size_t xt_size = sizeof(*xt) + sizeof(struct data_chunk);

	fbdev->vdma = of_dma_request_slave_channel(dev->of_node, "vdma");
	if (IS_ERR(fbdev->vdma)) {
		dev_err(dev, "Failed to request vdma channel");
		return PTR_ERR(fbdev->vdma);
	}

	dmaengine_terminate_all(fbdev->vdma);

	xt = kzalloc(xt_size, GFP_KERNEL);
	if (!xt)
		return -ENOMEM;

	xt->dir = DMA_MEM_TO_DEV;
	xt->numf =  info->var.yres;
	xt->sgl[0].size = info->fix.line_length;
	xt->frame_size = 1;
	xt->sgl[0].icg = 0;
	xt->src_start = info->fix.smem_start;
	xt->src_sgl = 1;
	xt->src_inc = 1;
	xt->dst_inc = 0;
	xt->dst_sgl = 0;

	tx_desc = dmaengine_prep_interleaved_dma(fbdev->vdma, xt, DMA_PREP_INTERRUPT);
	if (!tx_desc) {
		dev_err(dev, "Failed to prepare DMA descriptor");
		kfree(xt);
		dma_release_channel(fbdev->vdma);
		return -1;
	}

	config.frm_cnt_en = 0;
	/* Only one framebuffer address is submitted; never cycle unused slots. */
	config.park = 1;
	config.park_frm = 0;
	anlogic_vdma_channel_set_config(fbdev->vdma, &config);

	dmaengine_submit(tx_desc);
	dma_async_issue_pending(fbdev->vdma);
	kfree(xt);

	return 0;
}

static int vdmafb_vtc_init(struct vdmafb_dev *fbdev, struct videomode *vmode)
{
	void __iomem *vtc_base = fbdev->vtc_base;

	writel(0x0, vtc_base + VTC_RESET);
	udelay(10);
	writel(vmode->hfront_porch, vtc_base + VTC_HFRONT);
	writel(vmode->hactive, vtc_base + VTC_HACTIVE);
	writel(vmode->hsync_len, vtc_base + VTC_HSYNC);
	writel(vmode->hback_porch, vtc_base + VTC_HBACK);

	writel(vmode->vfront_porch, vtc_base + VTC_VFRONT);
	writel(vmode->vactive, vtc_base + VTC_VACTIVE);
	writel(vmode->vsync_len, vtc_base + VTC_VSYNC);
	writel(vmode->vback_porch, vtc_base + VTC_VBACK);

	writel(0x1, vtc_base + VTC_RESET);

	return 0;
}

static int vdmafb_get_timing_dt(struct vdmafb_dev *fbdev, struct videomode *vmode)
{
	struct device *dev = &fbdev->pdev->dev;
	int ret;

	ret = of_get_videomode(dev->of_node, vmode, OF_USE_NATIVE_MODE);
	if (ret < 0) {
		dev_err(dev, "Failed to get videomode from DT");
		return ret;
	}

	return 0;
}

static int vdmafb_setcolreg(unsigned int regno, unsigned int red,
	unsigned int green, unsigned int blue,
	unsigned int transp, struct fb_info *fb_info)
{
	u32 tmp;

	if (regno >= 16)
		return 1;

	red >>= 8; green >>= 8; blue >>= 8;
	tmp = (red << 16) | (green << 8) | blue;
	((u32 *)(fb_info->pseudo_palette))[regno] = tmp;

	return 0;
}

static int vdmafb_check_var(struct fb_var_screeninfo *var,
	struct fb_info *fb_info)
{
	struct fb_var_screeninfo *fb_var = &fb_info->var;

	memcpy(var, fb_var, sizeof(struct fb_var_screeninfo));
	return 0;
}

static const struct fb_ops vdmafb_ops = {
	.owner = THIS_MODULE,
	.fb_setcolreg = vdmafb_setcolreg,
	.fb_check_var = vdmafb_check_var,
	.fb_fillrect = cfb_fillrect,
	.fb_copyarea = cfb_copyarea,
	.fb_imageblit = cfb_imageblit,
};

static int vdmafb_fbinfo_init(struct vdmafb_dev *fbdev, struct videomode *vmode)
{
	int ret;
	unsigned int fb_size;
	dma_addr_t fb_phy;
	void *fb_virt;
	struct fb_videomode mode = {0};
	struct fb_info *fb_info = fbdev->info;

	ret = vdmafb_get_timing_dt(fbdev, vmode);
	if (ret < 0) {
		dev_err(&fbdev->pdev->dev, "vdmafb_get_timing_dt fail");
		return ret;
	}

	fb_size = vmode->hactive * vmode->vactive * 3;
	fb_virt = dma_alloc_wc(&fbdev->pdev->dev, PAGE_ALIGN(fb_size), &fb_phy, GFP_KERNEL);
	if (!fb_virt) {
		dev_err(&fbdev->pdev->dev, "allocate mem fail");
		return -ENOMEM;
	}

	dev_info(&fbdev->pdev->dev, "fb_phy = 0x%llx", fb_phy);
	memset(fb_virt, 0xff, fb_size);

	fb_info->fbops = &vdmafb_ops;
	fb_info->flags = FBINFO_FLAG_DEFAULT;
	fb_info->screen_base = fb_virt;
	fb_info->screen_size = fb_size;

	strcpy(fb_info->fix.id, "anlogic");
	fb_info->fix.type = FB_TYPE_PACKED_PIXELS;
	fb_info->fix.visual = FB_VISUAL_TRUECOLOR;
	fb_info->fix.accel = FB_ACCEL_NONE;
	fb_info->fix.line_length = vmode->hactive * 3;
	fb_info->fix.smem_start = fb_phy;
	fb_info->fix.smem_len = fb_size;

	fb_info->var.grayscale = 0;
	fb_info->var.nonstd = 0;
	fb_info->var.activate = FB_ACTIVATE_NOW;
	fb_info->var.accel_flags = FB_ACCEL_NONE;
	fb_info->var.bits_per_pixel = 24;

	fb_info->var.xres = fb_info->var.xres_virtual = vmode->hactive;
	fb_info->var.yres = fb_info->var.yres_virtual = vmode->vactive;
	fb_info->var.xoffset = fb_info->var.yoffset = 0;

	fb_info->var.red.offset = 16;
	fb_info->var.red.length = 8;
	fb_info->var.green.offset = 8;
	fb_info->var.green.length = 8;
	fb_info->var.blue.offset = 0;
	fb_info->var.blue.length = 8;
	fb_info->var.transp.offset = 0;
	fb_info->var.transp.length = 0;

	fb_videomode_from_videomode(vmode, &mode);
	fb_videomode_to_var(&fb_info->var, &mode);

	return 0;
}

static int vdmafb_probe(struct platform_device *pdev)
{
	struct vdmafb_dev *fbdev;
	struct fb_info *info;
	struct videomode vmode;
	int ret = 0;

	dev_info(&pdev->dev, "vdmafb probe");

	info = framebuffer_alloc(sizeof(struct vdmafb_dev), &pdev->dev);
	if (!info) {
		dev_err(&pdev->dev, "Failed to allocate memory");
		return -ENOMEM;
	}

	fbdev = info->par;
	fbdev->info = info;
	fbdev->pdev = pdev;

	fbdev->vtc_base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(fbdev->vtc_base)) {
		dev_err(&pdev->dev, "!fbdev->vtc_base");
		ret = -ENOMEM;
		goto out1;
	}

	ret = vdmafb_fbinfo_init(fbdev, &vmode);
	if (ret != 0) {
		dev_err(&pdev->dev, "vdmafb_fbinfo_init fail");
		goto out1;
	}

	ret = fb_alloc_cmap(&info->cmap, 256, 0);
	if (ret < 0) {
		dev_err(&pdev->dev, "Failed to allocate color map");
		goto out2;
	}

	info->pseudo_palette = devm_kzalloc(&pdev->dev, sizeof(u32) * 16, GFP_KERNEL);
		if (!info->pseudo_palette) {
			ret = -ENOMEM;
			goto out3;
	}

	ret = vdmafb_vtc_init(fbdev, &vmode);
	if (ret != 0) {
		dev_err(&pdev->dev, "vdmafb_vtc_init fail");
		goto out3;
	}

	ret = vdmafb_vdma_init(fbdev);
	if (ret != 0) {
		dev_err(&pdev->dev, "vdmafb_vdma_init fail");
		goto out4;
	}

	ret = register_framebuffer(info);
	if (ret < 0) {
		dev_err(&pdev->dev, "Failed to register framebuffer device");
		goto out4;
	}

	platform_set_drvdata(pdev, fbdev);
	return 0;

out4:
	if (!IS_ERR(fbdev->vdma)) {
		dmaengine_terminate_all(fbdev->vdma);
		dma_release_channel(fbdev->vdma);
	}
out3:
	fb_dealloc_cmap(&info->cmap);
out2:
	dma_free_wc(&pdev->dev, info->screen_size,
		info->screen_base, info->fix.smem_start);
out1:
	framebuffer_release(info);
	return ret;
}

static int vdmafb_remove(struct platform_device *pdev)
{
	struct vdmafb_dev *fbdev = platform_get_drvdata(pdev);
	struct fb_info *info = fbdev->info;

	unregister_framebuffer(info);
	dmaengine_terminate_all(fbdev->vdma);
	dma_release_channel(fbdev->vdma);
	fb_dealloc_cmap(&info->cmap);
	dma_free_wc(&pdev->dev, info->screen_size,
		info->screen_base, info->fix.smem_start);
	framebuffer_release(info);
	return 0;
}

static void vdmafb_shutdown(struct platform_device *pdev)
{
}

static const struct of_device_id vdmafb_of_match_table[] = {
	{ .compatible = "anlogic,vdmafb", },
	{ /* end of table */ },
};
MODULE_DEVICE_TABLE(of, vdmafb_of_match_table);

static struct platform_driver anlogic_vdmafb_driver = {
	.probe = vdmafb_probe,
	.remove = vdmafb_remove,
	.shutdown = vdmafb_shutdown,
	.driver = {
		.name = "anlogic-vdma-fb",
		.of_match_table = vdmafb_of_match_table,
	},
};

module_platform_driver(anlogic_vdmafb_driver);

MODULE_DESCRIPTION("Anlogic framebuffer driver");
MODULE_AUTHOR("Guanghao.zhang <guanghao.zhang@anlogic.com>");
MODULE_LICENSE("GPL");
