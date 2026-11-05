// SPDX-License-Identifier: GPL-2.0+
/*
 * anlogic reset Controller Driver
 */

#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/reset-controller.h>
#include <linux/of.h>
#include <linux/of_device.h>
#include <linux/err.h>
#include <linux/delay.h>
#include <linux/of_gpio.h>

/* define for reset assert and deassert values */
#define RESET_ASSERT 1
#define RESET_DEASSERT 0

struct anlogic_reset_data {
	struct reset_controller_dev rcdev; // reset controller device structure
	struct gpio_desc **reset_gpios;    // array of reset GPIO descriptors
	unsigned int *reset_delays;        // array of reset delays (in milliseconds)
	unsigned int *reset_post_delays;   // array of post reset delays (in milliseconds)
	unsigned int num_resets;           // number of reset lines
};

static int anlogic_reset_assert(struct reset_controller_dev *rcdev, unsigned long id)
{
	struct anlogic_reset_data *priv = container_of(rcdev, struct anlogic_reset_data, rcdev);

	if (id >= priv->num_resets || !priv->reset_gpios[id])
		return -EINVAL;

	/* assert the reset by setting the logical state to high */
	gpiod_direction_output(priv->reset_gpios[id], RESET_ASSERT);
	gpiod_set_value(priv->reset_gpios[id], RESET_ASSERT);

	return 0;
}

static int anlogic_reset_deassert(struct reset_controller_dev *rcdev, unsigned long id)
{
	struct anlogic_reset_data *priv = container_of(rcdev, struct anlogic_reset_data, rcdev);

	if (id >= priv->num_resets || !priv->reset_gpios[id])
		return -EINVAL;

	gpiod_direction_output(priv->reset_gpios[id], RESET_ASSERT);
	gpiod_set_value(priv->reset_gpios[id], RESET_ASSERT);

	/* delay for the specified time */
	mdelay(priv->reset_delays[id]);

	/* deassert the reset by setting the logical state to low */
	gpiod_set_value(priv->reset_gpios[id], RESET_DEASSERT);

	if (priv->reset_post_delays[id])
		mdelay(priv->reset_post_delays[id]);

	return 0;
}

static const struct reset_control_ops anlogic_reset_ops = {
	.assert = anlogic_reset_assert,
	.deassert = anlogic_reset_deassert,
};

static int anlogic_reset_probe(struct platform_device *pdev)
{
	struct anlogic_reset_data *priv;
	struct device_node *np = pdev->dev.of_node;
	int num_resets, i;
	u32 delays;

	num_resets = of_gpio_named_count(np, "reset-gpios");
	if (num_resets < 0)
		return num_resets;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->reset_gpios = devm_kzalloc(&pdev->dev,
					num_resets * sizeof(struct gpio_desc *),
					GFP_KERNEL);
	priv->reset_delays = devm_kzalloc(&pdev->dev,
					num_resets * sizeof(unsigned int),
					GFP_KERNEL);
	priv->reset_post_delays = devm_kzalloc(&pdev->dev,
					num_resets * sizeof(unsigned int),
					GFP_KERNEL);
	if (!priv->reset_gpios || !priv->reset_delays || !priv->reset_post_delays)
		return -ENOMEM;

	/* initialize the reset GPIOs and delays */
	for (i = 0; i < num_resets; i++) {
		priv->reset_gpios[i] = devm_gpiod_get_index(&pdev->dev, "reset",
								i, GPIOD_ASIS);
		if (IS_ERR(priv->reset_gpios[i])) {
			dev_err(&pdev->dev,
				"Failed to get reset GPIO %d: %ld\n", i,
				 PTR_ERR(priv->reset_gpios[i]));
			return PTR_ERR(priv->reset_gpios[i]);
		}
		/* get the reset delay for each GPIO from the device tree */
		if (of_property_read_u32_index(np, "reset-delays", i, &delays)) {
			dev_err(&pdev->dev, "Failed to get reset delay\n");
			return -EINVAL;
		}
		priv->reset_delays[i] = delays;
		/* get the post delay for each GPIO from the device tree */
		if (of_property_read_u32_index(np, "reset-post-delays", i, &delays)) {
			dev_err(&pdev->dev, "Failed to get reset post delay\n");
			return -EINVAL;
		}
		priv->reset_post_delays[i] = delays;
	}

	priv->num_resets = num_resets;
	priv->rcdev.owner = THIS_MODULE;
	priv->rcdev.nr_resets = num_resets;
	priv->rcdev.ops = &anlogic_reset_ops;
	priv->rcdev.of_node = np;
	priv->rcdev.of_reset_n_cells = 1;

	return devm_reset_controller_register(&pdev->dev, &priv->rcdev);
}


static const struct of_device_id anlogic_reset_of_match[] = {
	{ .compatible = "anlogic,reset-controller", },
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, anlogic_reset_of_match);

static struct platform_driver anlogic_reset_driver = {
	.probe = anlogic_reset_probe,
	.driver = {
		.name = "anlogic-reset",
		.of_match_table = anlogic_reset_of_match,
	},
};

module_platform_driver(anlogic_reset_driver);

MODULE_AUTHOR("Naiyuan Que <naiyuan.que@anlogic.com>");
MODULE_DESCRIPTION("anlogic reset Controller Driver");
MODULE_LICENSE("GPL");
