// SPDX-License-Identifier: GPL-2.0
/* Fractional calculation from Anlogic SDK2026.02, commit a90803aa12fff9f6adefe653a5d40282bc928c1a.
 * Kept separate from framebuffer to preserve the installed R46 device-tree ABI.
 * This release supports only the observed 75 MHz -> 74.25 MHz 720p profile.
 */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/io.h>
#include <linux/of.h>
#include <linux/delay.h>
#define PLL_VCO_MIN_HZ          800000000UL
#define PLL_VCO_MAX_HZ          2000000000UL
#define PLL_VCO_PREFERRED_MIN_HZ 1600000000UL
#define PLL_N_MIN               1
#define PLL_N_MAX               127
#define PLL_M_INT_MIN           3
#define PLL_M_INT_MAX           126
#define PLL_C_MIN               1
#define PLL_C_MAX               128
#define FRAC_PRECISION          4096
#define MIN_DUTY_CYCLES         4
struct pll_config_t {
	unsigned long clk_in_hz;
	unsigned long clk_out_hz;
	int n_div;
	int m_div_int;
	int m_div_frac;
	int c_div;
	unsigned long vco_freq_hz;
	unsigned long actual_clk_out_hz;
	int error_ppm;
	int duty_ratio_percent;
};

static int calculate_pll_params_simplified(struct pll_config_t *config, struct device *dev)
{
	int n, c;
	int best_n = 0, best_c = 0, best_m_scaled = 0;
	int best_error = INT_MAX;
	unsigned long long m_total_scaled;

	if (!config)
		return -EINVAL;

	dev_dbg(dev, "Simplified PLL calculation: input=%lu Hz, target=%lu Hz\n",
		config->clk_in_hz, config->clk_out_hz);

	for (n = PLL_N_MIN; n <= PLL_N_MAX; n++) {
		for (c = PLL_C_MIN; c <= PLL_C_MAX; c++) {
			unsigned long long vco_scaled;
			unsigned long long m_scaled;
			int m_int;
			unsigned long long actual_vco_hz;
			unsigned long long actual_out_hz;
			unsigned long long diff;
			int error_ppm;
			int quality_score;
			bool is_better;

			vco_scaled = (unsigned long long)config->clk_out_hz *
							c * FRAC_PRECISION;
			m_scaled = (vco_scaled * n) / config->clk_in_hz;
			m_int = (int)(m_scaled / FRAC_PRECISION);

			if (m_int < PLL_M_INT_MIN || m_int > PLL_M_INT_MAX)
				continue;

			actual_vco_hz = (config->clk_in_hz * m_scaled) /
						       ((unsigned long long)n * FRAC_PRECISION);
			if (actual_vco_hz < PLL_VCO_MIN_HZ || actual_vco_hz > PLL_VCO_MAX_HZ)
				continue;

			actual_out_hz = actual_vco_hz / c;
			diff = (actual_out_hz > config->clk_out_hz) ?
					      (actual_out_hz - config->clk_out_hz) :
					      (config->clk_out_hz - actual_out_hz);
			error_ppm = (int)((diff * 1000000ULL) / config->clk_out_hz);
			quality_score = 0;

			if (actual_vco_hz > PLL_VCO_PREFERRED_MIN_HZ)
				quality_score += 100;
			if (c >= MIN_DUTY_CYCLES)
				quality_score += 50;
			if (c % 2 == 0)
				quality_score += 25;

			is_better = false;

			if (error_ppm < best_error)
				is_better = true;
			else if (error_ppm == best_error && quality_score > 0)
				is_better = true;

			if (is_better) {
				best_error = error_ppm;
				best_n = n;
				best_c = c;
				best_m_scaled = (int)m_scaled;

				if (error_ppm <= 10)
					break;
			}
		}
		if (best_error <= 10)
			break;
	}

	if (best_n == 0 || best_c == 0 || best_m_scaled == 0) {
		dev_err(dev, "Failed to find valid PLL parameters\n");
		return -EINVAL;
	}

	config->n_div = best_n;
	config->c_div = best_c;
	config->m_div_int = best_m_scaled / FRAC_PRECISION;
	config->m_div_frac = best_m_scaled % FRAC_PRECISION;

	m_total_scaled = (unsigned long long)config->m_div_int * FRAC_PRECISION +
					    config->m_div_frac;
	config->vco_freq_hz = (config->clk_in_hz * m_total_scaled) /
			((unsigned long long)config->n_div * FRAC_PRECISION);
	config->actual_clk_out_hz = config->vco_freq_hz / config->c_div;
	config->error_ppm = best_error;
	config->duty_ratio_percent = (config->c_div % 2 == 0) ? 50 :
			 ((config->c_div + 1) * 50) / config->c_div;

	return 0;
}


static int r46_dynclk_probe(struct platform_device *pdev)
{
    struct pll_config_t c = {0};
    u32 ref, out, regs[6];
    const u32 expected[6] = {0x0400, 0x1289, 0x103d, 0x110e, 0x270a, 0x2406};
    void __iomem *base;
    int i, ret;
    if (of_property_read_u32(pdev->dev.of_node, "refclk", &ref) ||
        of_property_read_u32(pdev->dev.of_node, "expclk", &out))
        return -EINVAL;
    if (ref != 75000000 || out != 74250000)
        return dev_err_probe(&pdev->dev, -EINVAL, "Unreviewed R46 clock profile\n");
    c.clk_in_hz = ref; c.clk_out_hz = out;
    ret = calculate_pll_params_simplified(&c, &pdev->dev);
    if (ret) return ret;
    regs[0] = 0x0400 | ((c.n_div - 1) & 255);
    regs[1] = 0x1200 | (((c.m_div_int - 1) | 0x80) & 255);
    regs[2] = 0x1000 | (c.m_div_frac & 255);
    regs[3] = 0x1100 | ((c.m_div_frac >> 8) & 15);
    regs[4] = 0x2700 | ((c.c_div - 1) & 255);
    regs[5] = 0x2400 | (((c.c_div + 1) / 2) & 255);
    for (i = 0; i < 6; i++)
        if (regs[i] != expected[i])
            return dev_err_probe(&pdev->dev, -EINVAL, "PLL result differs from installed profile\n");
    base = devm_platform_ioremap_resource(pdev, 0);
    if (IS_ERR(base)) return PTR_ERR(base);
    writel(0, base + 0x0c);
    for (i = 0; i < 6; i++) {
        writel(regs[i], base);
        dev_info(&pdev->dev, "R46 PLL register word 0x%04x\n", regs[i]);
    }
    for (i = 0; i < 100; i++) {
        udelay(10);
        if (readl(base + 0x08) & 1) break;
    }
    /* Preserve the original driver's bounded wait and output-enable sequence. */
    writel(1, base + 0x0c);
    dev_info(&pdev->dev, "R46 720p clock actual=%lu Hz error=%d ppm lock=%u\n",
             c.actual_clk_out_hz, c.error_ppm, readl(base + 0x08) & 1);
    return 0;
}
static const struct of_device_id r46_dynclk_match[] = {
    { .compatible = "anlogic,dynclk" }, { }
};
MODULE_DEVICE_TABLE(of, r46_dynclk_match);
static struct platform_driver r46_dynclk_driver = {
    .probe = r46_dynclk_probe,
    .driver = { .name = "anlogic-dynclk", .of_match_table = r46_dynclk_match },
};
module_platform_driver(r46_dynclk_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("R46 verified 720p fractional clock profile");
