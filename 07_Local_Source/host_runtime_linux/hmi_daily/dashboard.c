#define _GNU_SOURCE
#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#endif
#include "lvgl.h"
#include "fonts/ui_fonts.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <signal.h>
#include <time.h>
#include <math.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#ifndef CABINET_HEADLESS
#include "src/drivers/display/fb/lv_linux_fbdev.h"
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <linux/fb.h>
#include <linux/kd.h>
#endif

#define BG        0x0b0f15
#define PANEL     0x141b24
#define SUBPANEL  0x0e141c
#define HEADER_BG 0x1c2632
#define EDGE      0x283442
#define TEXT      0xe6edf3
#define MUTED     0x8899a8
#define DARK_TEXT 0x091318
#define TEAL      0x39d5ff
#define BLUE      0x4888f0
#define AMBER     0xf4bc62
#define GREEN     0x19e37c
#define RED       0xff5252
#define WIDTH     1280
#define HEIGHT    720

typedef struct { char key[64]; char value[513]; } field_t;
typedef struct { lv_obj_t *title, *value, *unit, *note, *bar; } metric_t;

static field_t fields[512];
static size_t field_count;
static const char *state_path;
static lv_obj_t *title_label, *header_meta_label;
static lv_obj_t *banner, *banner_title, *footer;
static metric_t metrics[4];
static lv_obj_t *matrix[6][3], *ratio_box, *ratio_label;
static lv_obj_t *matrix_title, *matrix_headers[3];
static lv_obj_t *trend_chart, *trend_empty, *trend_max, *trend_mid;
static lv_obj_t *trend_title, *trend_unit;
static int thermal_chart_mode;
static lv_obj_t *temperature_chart, *temperature_ticks[3], *control_tracking_note, *control_pwm_note, *trend_values[3];
static lv_obj_t *inlet_label;
static lv_chart_series_t *rpm_series, *temp_series, *target_series;
static lv_obj_t *band_chart, *band_empty, *band_labels[8];
static lv_chart_series_t *band_series[2];
static lv_obj_t *icm_raw_panel, *icm_raw_lines[2], *icm_raw_info[2];
static lv_obj_t *pl_titles[5];
static lv_obj_t *pl_boxes[6], *pl_lights[5][9], *pl_sensor_dot, *pl_sensor_label, *pl_status_label;
static lv_obj_t *pl_state_labels[5];
static lv_obj_t *model_state, *model_note, *probability_labels[5], *probability_bars[5];
static lv_obj_t *baseline_title, *baseline_score, *baseline_bar, *baseline_badge, *baseline_badge_label, *baseline_scope;
static lv_obj_t *group_bars[4], *group_values[4];
static lv_obj_t *life_hours, *life_caption, *life_rpm, *life_detail, *life_note, *life_bar;
static uint64_t last_plot, sequence_progress;
static char previous_sequence[64], previous_plot_sequence[64], previous_contract[256];
static int link_valid, preview_mode, interface_mismatch;
static int nn_direct_used;
static int rpm_axis_max = 6000;

static uint64_t milliseconds(void) {
    struct timespec stamp;
    clock_gettime(CLOCK_MONOTONIC, &stamp);
    return (uint64_t)stamp.tv_sec * 1000 + stamp.tv_nsec / 1000000;
}

static const char *value(const char *key) {
    for(size_t index = 0; index < field_count; index++)
        if(strcmp(fields[index].key, key) == 0) return fields[index].value;
    return "--";
}

static int numeric(const char *key, double *result) {
    const char *text = value(key);
    char *end;
    double parsed = strtod(text, &end);
    if(end == text || *end || !isfinite(parsed) || fabs(parsed) > 1000000000) return 0;
    *result = parsed;
    return 1;
}

static int deadline_current(const char *key) {
    const char *text = value(key);
    char *end;
    if(*text < '0' || *text > '9') return 0;
    unsigned long long deadline = strtoull(text, &end, 10);
    uint64_t now = milliseconds();
    return end != text && !*end && deadline >= now && deadline - now <= 2500;
}

static int environment_current(const char *key) {
    return link_valid && deadline_current(key);
}

static void set_text(lv_obj_t *object, const char *text) {
    if(strcmp(lv_label_get_text(object), text) != 0) lv_label_set_text(object, text);
}

/* LVGL invalidates an object even when a style setter repeats its current
   value. Keep the 50 ms expiry checks without repainting static panels. */
static void set_text_color(lv_obj_t *object, lv_color_t color, lv_part_t part) {
    if(!lv_color_eq(lv_obj_get_style_text_color(object, part), color))
        lv_obj_set_style_text_color(object, color, part);
}

static void set_bg_color(lv_obj_t *object, lv_color_t color, lv_part_t part) {
    if(!lv_color_eq(lv_obj_get_style_bg_color(object, part), color))
        lv_obj_set_style_bg_color(object, color, part);
}

static void set_border_color(lv_obj_t *object, lv_color_t color, lv_part_t part) {
    if(!lv_color_eq(lv_obj_get_style_border_color(object, part), color))
        lv_obj_set_style_border_color(object, color, part);
}

static lv_obj_t *panel_styled(lv_obj_t *parent, int left, int top, int width, int height, uint32_t bg, uint32_t border, int radius) {
    lv_obj_t *object = lv_obj_create(parent);
    lv_obj_remove_style_all(object);
    lv_obj_set_pos(object, left, top);
    lv_obj_set_size(object, width, height);
    lv_obj_set_style_bg_color(object, lv_color_hex(bg), 0);
    lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(object, lv_color_hex(border), 0);
    lv_obj_set_style_border_width(object, border ? 1 : 0, 0);
    lv_obj_set_style_radius(object, radius, 0);
    lv_obj_remove_flag(object, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    return object;
}

static lv_obj_t *panel(lv_obj_t *parent, int left, int top, int width, int height, uint32_t color) {
    return panel_styled(parent, left, top, width, height, color, EDGE, 4);
}

static lv_obj_t *label_aligned(lv_obj_t *parent, int left, int top, int width, const lv_font_t *font, uint32_t color, lv_text_align_t align, const char *text) {
    lv_obj_t *object = lv_label_create(parent);
    lv_obj_set_pos(object, left, top);
    lv_obj_set_width(object, width);
    lv_obj_set_style_text_font(object, font, 0);
    lv_obj_set_style_text_color(object, lv_color_hex(color), 0);
    lv_obj_set_style_text_align(object, align, 0);
    lv_label_set_long_mode(object, LV_LABEL_LONG_CLIP);
    lv_label_set_text(object, text);
    return object;
}

static lv_obj_t *label(lv_obj_t *parent, int left, int top, int width, const lv_font_t *font, uint32_t color, const char *text) {
    return label_aligned(parent, left, top, width, font, color, LV_TEXT_ALIGN_LEFT, text);
}

static lv_obj_t *bar(lv_obj_t *parent, int left, int top, int width, int height, uint32_t color) {
    lv_obj_t *object = lv_bar_create(parent);
    lv_obj_remove_style_all(object);
    lv_obj_set_pos(object, left, top);
    lv_obj_set_size(object, width, height);
    lv_obj_set_style_bg_color(object, lv_color_hex(0x222c37), 0);
    lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(object, 2, 0);
    lv_obj_set_style_bg_color(object, lv_color_hex(color), LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(object, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_radius(object, 2, LV_PART_INDICATOR);
    lv_obj_remove_flag(object, LV_OBJ_FLAG_CLICKABLE);
    lv_bar_set_range(object, 0, 1000);
    return object;
}

static void bar_value(lv_obj_t *object, double fraction, int valid, uint32_t color) {
    double bounded = fraction < 0 ? 0 : fraction > 1 ? 1 : fraction;
    lv_bar_set_value(object, valid ? (int32_t)lround(bounded * 1000) : 0, LV_ANIM_OFF);
    set_bg_color(object, lv_color_hex(valid ? color : 0x222c37), LV_PART_INDICATOR);
}

static void chart_style(lv_obj_t *chart) {
    lv_obj_set_style_bg_color(chart, lv_color_hex(SUBPANEL), 0);
    lv_obj_set_style_bg_opa(chart, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(chart, lv_color_hex(EDGE), 0);
    lv_obj_set_style_border_width(chart, 1, 0);
    lv_obj_set_style_radius(chart, 2, 0);
    lv_obj_set_style_pad_all(chart, 2, 0);
    lv_obj_set_style_line_color(chart, lv_color_hex(0x1f2a36), LV_PART_MAIN);
    lv_obj_set_style_line_width(chart, 2, LV_PART_ITEMS);
    lv_obj_set_style_size(chart, 0, 0, LV_PART_INDICATOR);
    lv_obj_remove_flag(chart, LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_SCROLLABLE);
}

static void create_metrics(lv_obj_t *screen) {
    const char *names[4] = {"风机转速", "核心温度", "风机电流", "风道压差"};
    for(int index = 0; index < 4; index++) {
        lv_obj_t *card = panel(screen, 12 + index % 2 * 186, 68 + index / 2 * 160, 174, 148, PANEL);
        metrics[index].title = label(card, 12, 10, index == 0 ? 100 : 150, index == 2 ? &ui_zh_16 : &ui_zh_18, TEXT, names[index]);
        metrics[index].value = label_aligned(card, 8, 34, 158, &lv_font_montserrat_44,
                                            MUTED, LV_TEXT_ALIGN_CENTER, "--");
        metrics[index].unit = label_aligned(card, 8, 85, 158, &ui_zh_16, MUTED, LV_TEXT_ALIGN_CENTER, "--");
        metrics[index].note = label_aligned(card, 8, 109, 158, &ui_zh_16, MUTED, LV_TEXT_ALIGN_CENTER, "等待有效采样");
        metrics[index].bar = index == 0 || index == 3 ? bar(card, 12, 130, 150, 5, TEAL) : NULL;
    }
}

static void create_trend(lv_obj_t *screen) {
    lv_obj_t *card=panel(screen,12,388,360,304,PANEL);
    trend_title=label(card,12,10,336,&ui_zh_18,TEXT,"转速 / 核心温度 · 60s");
    trend_values[0]=label(card,12,38,108,&ui_zh_16,TEAL,"实测 --");
    trend_values[1]=label(card,126,38,108,&ui_zh_16,BLUE,"目标 --");
    trend_values[2]=label(card,240,38,108,&ui_zh_16,AMBER,"核心 --℃");
    trend_unit=label(card,6,59,38,&lv_font_montserrat_12,MUTED,"RPM");
    label(card,324,58,30,&ui_zh_16,AMBER,"℃");
    trend_chart=lv_chart_create(card);lv_obj_set_pos(trend_chart,48,80);lv_obj_set_size(trend_chart,264,124);
    temperature_chart=trend_chart;
    chart_style(trend_chart);lv_chart_set_type(trend_chart,LV_CHART_TYPE_LINE);lv_chart_set_point_count(trend_chart,61);
    lv_chart_set_axis_range(trend_chart,LV_CHART_AXIS_PRIMARY_Y,0,6000);
    lv_chart_set_axis_range(trend_chart,LV_CHART_AXIS_SECONDARY_Y,200,800);
    lv_chart_set_div_line_count(trend_chart,5,7);
    target_series=lv_chart_add_series(trend_chart,lv_color_hex(BLUE),LV_CHART_AXIS_PRIMARY_Y);
    rpm_series=lv_chart_add_series(trend_chart,lv_color_hex(TEAL),LV_CHART_AXIS_PRIMARY_Y);
    temp_series=lv_chart_add_series(trend_chart,lv_color_hex(AMBER),LV_CHART_AXIS_SECONDARY_Y);
    lv_chart_set_all_values(trend_chart,rpm_series,LV_CHART_POINT_NONE);
    lv_chart_set_all_values(trend_chart,target_series,LV_CHART_POINT_NONE);
    lv_chart_set_all_values(trend_chart,temp_series,LV_CHART_POINT_NONE);
    trend_max=label_aligned(card,2,76,40,&lv_font_montserrat_12,MUTED,LV_TEXT_ALIGN_RIGHT,"6000");
    trend_mid=label_aligned(card,2,136,40,&lv_font_montserrat_12,MUTED,LV_TEXT_ALIGN_RIGHT,"3000");
    label_aligned(card,2,196,40,&lv_font_montserrat_12,MUTED,LV_TEXT_ALIGN_RIGHT,"0");
    for(int i=0;i<3;i++) temperature_ticks[i]=label(card,318,76+i*60,36,&lv_font_montserrat_12,AMBER,i==0?"80":i==1?"50":"20");
    label(card,48,211,48,&lv_font_montserrat_12,MUTED,"-60s");
    label_aligned(card,158,211,48,&lv_font_montserrat_12,MUTED,LV_TEXT_ALIGN_CENTER,"-30s");
    label_aligned(card,264,211,48,&lv_font_montserrat_12,MUTED,LV_TEXT_ALIGN_RIGHT,"0s");
    trend_empty=label_aligned(card,62,130,236,&ui_zh_16,MUTED,LV_TEXT_ALIGN_CENTER,"等待有效数据");
    control_tracking_note=label(card,12,233,336,&ui_zh_16,MUTED,"闭环未启用 · 仅采集");
    control_pwm_note=label(card,12,255,336,&ui_zh_16,MUTED,"PWM --% · 转速误差 --");
    inlet_label=label(card,12,278,336,&ui_zh_16,TEAL,"进风 --℃ · RH --% | AHT20");
}

static void create_vibration(lv_obj_t *screen) {
    lv_obj_t *card = panel(screen, 384, 68, 500, 308, PANEL);
    matrix_title = label(card, 12, 10, 470, &ui_zh_18, TEXT, "双测点时域特征矩阵 (18维)");
    lv_obj_t *hdr = panel_styled(card, 10, 38, 480, 26, HEADER_BG, 0, 2);
    const char *headers[4] = {"测点 / 轴向", "RMS (g)", "P-P (g)", "Kurtosis"};
    const int columns[4] = {14, 168, 282, 392};
    for(int column = 0; column < 4; column++) {
        lv_obj_t *heading=label(hdr, columns[column], 4, 104, &ui_zh_16, TEXT, headers[column]);
        if(column) matrix_headers[column-1]=heading;
    }

    lv_obj_t *group_a = panel_styled(card, 10, 66, 86, 88, TEAL, 0, 2);
    label_aligned(group_a, 2, 20, 82, &ui_zh_18, DARK_TEXT, LV_TEXT_ALIGN_CENTER, "测点A");
    label_aligned(group_a, 2, 46, 82, &lv_font_montserrat_12, DARK_TEXT, LV_TEXT_ALIGN_CENTER, "(Fan Casing)");

    lv_obj_t *group_b = panel_styled(card, 10, 158, 86, 88, BLUE, 0, 2);
    label_aligned(group_b, 2, 20, 82, &ui_zh_18, DARK_TEXT, LV_TEXT_ALIGN_CENTER, "测点B");
    label_aligned(group_b, 2, 46, 82, &lv_font_montserrat_12, DARK_TEXT, LV_TEXT_ALIGN_CENTER, "(Rack Base)");

    for(int row = 0; row < 6; row++) {
        int top = 66 + row * 30 + (row >= 3 ? 4 : 0);
        panel_styled(card, 98, top, 392, 28, row % 2 ? PANEL : 0x18212c, 0, 0);
        char text[24];
        snprintf(text, sizeof(text), "%c - %c", row < 3 ? 'A' : 'B', "XYZ"[row % 3]);
        label(card, 108, top + 4, 64, &ui_zh_18, TEXT, text);
        for(int column = 0; column < 3; column++)
            matrix[row][column] = label(card, columns[column + 1] + 10, top + 4, 96, &lv_font_montserrat_20, TEXT, "--");
    }
    ratio_box = panel_styled(card, 10, 258, 480, 36, 0x102329, 0x2b7a80, 4);
    ratio_label = label_aligned(ratio_box, 8, 8, 464, &ui_zh_16, TEAL, LV_TEXT_ALIGN_CENTER, "A/B 径向比 -- · 模型输入 --");
}

static void create_spectrum(lv_obj_t *screen) {
    lv_obj_t *card = panel(screen, 384, 388, 500, 304, PANEL);
    label(card, 12, 10, 360, &ui_zh_18, TEXT, "1024点 FFT 八频带能量占比 (16维)");
    panel_styled(card, 396, 14, 12, 12, TEAL, 0, 2);
    label(card, 412, 11, 32, &lv_font_montserrat_16, TEXT, "A");
    panel_styled(card, 440, 14, 12, 12, BLUE, 0, 2);
    label(card, 456, 11, 32, &lv_font_montserrat_16, TEXT, "B");
    band_chart = lv_chart_create(card);
    lv_obj_set_pos(band_chart, 42, 46);
    lv_obj_set_size(band_chart, 444, 194);
    chart_style(band_chart);
    lv_chart_set_type(band_chart, LV_CHART_TYPE_BAR);
    lv_chart_set_point_count(band_chart, 8);
    lv_chart_set_axis_range(band_chart, LV_CHART_AXIS_PRIMARY_Y, 0, 1000);
    lv_chart_set_div_line_count(band_chart, 5, 0);
    for(int point = 0; point < 2; point++) {
        band_series[point] = lv_chart_add_series(band_chart, lv_color_hex(point ? BLUE : TEAL), LV_CHART_AXIS_PRIMARY_Y);
        lv_chart_set_all_values(band_chart, band_series[point], LV_CHART_POINT_NONE);
    }
    label(card, 4, 44, 36, &lv_font_montserrat_12, MUTED, "100%");
    label(card, 6, 90, 34, &lv_font_montserrat_12, MUTED, "75%");
    label(card, 6, 136, 34, &lv_font_montserrat_12, MUTED, "50%");
    label(card, 6, 182, 34, &lv_font_montserrat_12, MUTED, "25%");
    label(card, 20, 226, 20, &lv_font_montserrat_12, MUTED, "0");
    for(int band = 0; band < 8; band++) {
        char text[12];
        snprintf(text, sizeof(text), "B%d", band);
        label_aligned(card, 44 + band * 55, 246, 50, &lv_font_montserrat_16, TEXT, LV_TEXT_ALIGN_CENTER, text);
        band_labels[band] = label_aligned(card, 40 + band * 55, 268, 58, &lv_font_montserrat_12, MUTED, LV_TEXT_ALIGN_CENTER, "--");
    }
    band_empty = label_aligned(card, 110, 132, 330, &ui_zh_18, MUTED, LV_TEXT_ALIGN_CENTER, "等待合格的真实振动窗口");
    icm_raw_panel = panel_styled(card, 10, 40, 480, 248, SUBPANEL, EDGE, 4);
    label(icm_raw_panel, 12, 10, 456, &lv_font_montserrat_16, AMBER, "ICM SPI RAW / UNCALIBRATED");
    for(int point = 0; point < 2; point++) {
        icm_raw_lines[point] = label(icm_raw_panel, 12, 48 + point * 80, 456, &lv_font_montserrat_20,
                                   point ? BLUE : TEAL, point ? "B XYZ: --  --  --" : "A XYZ: --  --  --");
        icm_raw_info[point] = label(icm_raw_panel, 12, 78 + point * 80, 456, &lv_font_montserrat_12, MUTED, "waiting");
    }
    label(icm_raw_panel, 12, 214, 456, &lv_font_montserrat_12, AMBER, "RAW COUNTS ONLY / NOT FFT, RMS OR g");
    lv_obj_add_flag(icm_raw_panel, LV_OBJ_FLAG_HIDDEN);
}

static void create_decisions(lv_obj_t *screen) {
    /* Layer 1: PL Hardware Deterministic Protection (3x2 LED Matrix Sub-cards) */
    lv_obj_t *card = panel(screen, 896, 68, 372, 198, PANEL);
    label(card, 12, 10, 348, &ui_zh_18, TEXT, "第1层 · 硬件监测 / 实时告警");
    const char *zh_names[5] = {"过流", "过热", "堵转", "超速", "振动"};
    for(int index = 0; index < 5; index++) {
        int left = 12 + (index % 3) * 118, top = 34 + (index / 3) * 58;
        pl_boxes[index] = panel_styled(card, left, top, 112, 52, SUBPANEL, EDGE, 4);
        for(int dot = 0; dot < 9; dot++) {
            int dx = 10 + (dot % 3) * 9, dy = 11 + (dot / 3) * 9;
            pl_lights[index][dot] = panel_styled(pl_boxes[index], dx, dy, 6, 6, EDGE, 0, 2);
        }
        pl_titles[index]=label(pl_boxes[index], 44, 6, 64, &ui_zh_16, TEXT, zh_names[index]);
        pl_state_labels[index] = label(pl_boxes[index], 44, 27, 64, &ui_zh_16, AMBER, "预警");
    }
    pl_boxes[5] = panel_styled(card, 12 + 2 * 118, 34 + 58, 112, 52, SUBPANEL, EDGE, 4);
    pl_sensor_dot = panel_styled(pl_boxes[5], 10, 18, 14, 14, EDGE, 0, 4);
    label(pl_boxes[5], 34, 6, 74, &ui_zh_16, TEXT, "传感器");
    pl_sensor_label = label(pl_boxes[5], 34, 27, 74, &ui_zh_16, AMBER, "预警");
    label(card, 12, 150, 84, &ui_zh_16, GREEN, "正常");
    label(card, 128, 150, 84, &ui_zh_16, AMBER, "预警");
    label(card, 244, 150, 84, &ui_zh_16, RED, "报警");
    pl_status_label = label(card, 12, 174, 348, &ui_zh_16, MUTED, "保护状态待确认");

    /* Layer 2: NPU 5-Class Classification */
    card = panel(screen, 896, 276, 372, 208, PANEL);
    model_state = label(card, 12, 10, 348, &ui_zh_18, TEXT, "第2层 · 本地五分类推理 (Alnpu)");
    const char *classes[5] = {"正常", "失衡", "滤网堵塞", "过热", "卡死"};
    for(int index = 0; index < 5; index++) {
        int top = 40 + index * 28;
        probability_labels[index] = label(card, 12, top, 134, &ui_zh_16, index == 0 ? GREEN : TEXT, classes[index]);
        probability_bars[index] = bar(card, 148, top + 2, 212, 16, index == 0 ? GREEN : TEAL);
    }
    model_note = label(card, 12, 182, 348, &ui_zh_16, MUTED, "没有新鲜的真实模型结果");

    /* Layer 3: Operating Condition Health Baseline */
    card = panel(screen, 896, 494, 372, 198, PANEL);
    lv_obj_add_flag(card, LV_OBJ_FLAG_HIDDEN);
    baseline_title = label(card, 12, 10, 348, &ui_zh_18, TEXT, "第3层 · 工况健康基线");
    baseline_score = label(card, 12, 38, 348, &ui_zh_16, TEXT, "偏离度 -- / --");
    baseline_bar = bar(card, 12, 68, 348, 10, TEAL);
    baseline_badge = panel_styled(card, 84, 62, 52, 22, 0x1d4e6b, TEAL, 4);
    baseline_badge_label = label_aligned(baseline_badge, 2, 2, 48, &lv_font_montserrat_16, TEXT, LV_TEXT_ALIGN_CENTER, "--");
    const char *groups[4] = {"幅值", "谱形", "传递比", "过程量"};
    for(int index = 0; index < 4; index++) {
        int left = 12 + index * 88;
        group_bars[index] = bar(card, left, 98, 78, 8, TEAL);
        label_aligned(card, left, 112, 78, &ui_zh_16, MUTED, LV_TEXT_ALIGN_CENTER, groups[index]);
        group_values[index] = label_aligned(card, left, 132, 78, &lv_font_montserrat_12, TEXT, LV_TEXT_ALIGN_CENTER, "--");
    }
    lv_obj_t *scope_box = panel_styled(card, 12, 156, 348, 30, SUBPANEL, EDGE, 4);
    baseline_scope = label_aligned(scope_box, 8, 5, 332, &ui_zh_16, TEXT, LV_TEXT_ALIGN_CENTER, "网页双确认 · 观察模式");
    card = panel(screen, 896, 494, 372, 198, PANEL);
    label(card, 12, 10, 348, &ui_zh_18, TEXT, "设备剩余寿命 · 估算");
    life_hours = label(card, 12, 35, 290, &lv_font_montserrat_44, TEAL, "--");
    label(card, 316, 54, 40, &lv_font_montserrat_20, MUTED, "h");
    life_caption = label(card, 12, 86, 348, &ui_zh_16, MUTED, "等待寿命记录");
    life_bar = bar(card, 12, 110, 348, 6, TEAL);
    life_rpm = label(card, 12, 124, 348, &ui_zh_16, TEXT, "满速基准 -- · 复测 -- RPM");
    life_detail = label(card, 12, 148, 348, &ui_zh_16, MUTED, "衰减 -- · 工时 -- h");
    life_note = label(card, 12, 172, 348, &ui_zh_16, MUTED, "SD卡保存 · 等待实际满速");
}

#ifdef CABINET_RECORDING
#include "capture_view.h"
#endif
#include "parameter_view.h"

static void create_ui(void) {
    lv_obj_t *screen = lv_screen_active();
    lv_obj_remove_style_all(screen);
    lv_obj_set_style_bg_color(screen, lv_color_hex(BG), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);

    /* Top Header Bar */
    lv_obj_t *top_bar = panel_styled(screen, 0, 0, WIDTH, 58, 0x0f151d, EDGE, 0);
    title_label = label(top_bar, 14, 17, 420, &ui_zh_20, TEXT, "机柜风冷边缘智能测控 | WAIT");
    banner = panel_styled(top_bar, 442, 10, 396, 38, 0x0f2922, GREEN, 4);
    banner_title = label_aligned(banner, 8, 8, 380, &ui_zh_18, GREEN, LV_TEXT_ALIGN_CENTER, "[ WAIT · 等待有效采样 ]");
    header_meta_label = label_aligned(top_bar, 846, 19, 420, &ui_zh_16, MUTED, LV_TEXT_ALIGN_RIGHT, "FCB1/EDG1 未确认 | Fs --/-- Hz | 帧 #--");

    create_metrics(screen);
    create_trend(screen);
    create_vibration(screen);
    create_spectrum(screen);
    create_decisions(screen);
    footer = label(screen, 12, 698, 1256, &ui_zh_16, MUTED, "异常只告警 · PWM按温度运行 · 网页发起学习");
#ifdef CABINET_RECORDING
    create_capture_ui(screen);
#endif
    create_operator_ui(screen, top_bar);
}

static void clear_trend(void) {
    lv_chart_set_all_values(trend_chart,rpm_series,LV_CHART_POINT_NONE);
    lv_chart_set_all_values(trend_chart,target_series,LV_CHART_POINT_NONE);
    lv_chart_set_all_values(trend_chart,temp_series,LV_CHART_POINT_NONE);
    lv_obj_remove_flag(trend_empty,LV_OBJ_FLAG_HIDDEN);
    previous_plot_sequence[0]='\0';last_plot=0;
}

static void trend_point(int32_t rpm, int32_t target, int32_t temperature) {
    lv_chart_set_next_value(trend_chart,rpm_series,rpm);
    lv_chart_set_next_value(trend_chart,target_series,target);
    lv_chart_set_next_value(trend_chart,temp_series,temperature);
}

static void trend_ranges(void) {
    int32_t *rpms=lv_chart_get_series_y_array(trend_chart,rpm_series);
    int32_t *targets=lv_chart_get_series_y_array(trend_chart,target_series);
    int32_t *temperatures=lv_chart_get_series_y_array(trend_chart,temp_series);
    int32_t maximum=6000,low=200,high=800;int any=0;
    for(unsigned i=0;i<61;i++) {
        if(rpms[i]!=LV_CHART_POINT_NONE || targets[i]!=LV_CHART_POINT_NONE || temperatures[i]!=LV_CHART_POINT_NONE)any=1;
        if(rpms[i]!=LV_CHART_POINT_NONE && rpms[i]>maximum)maximum=rpms[i];
        if(targets[i]!=LV_CHART_POINT_NONE && targets[i]>maximum)maximum=targets[i];
        if(temperatures[i]!=LV_CHART_POINT_NONE) {
            if(temperatures[i]<low)low=temperatures[i];
            if(temperatures[i]>high)high=temperatures[i];
        }
    }
    if(any)lv_obj_add_flag(trend_empty,LV_OBJ_FLAG_HIDDEN);else lv_obj_remove_flag(trend_empty,LV_OBJ_FLAG_HIDDEN);
    rpm_axis_max=thermal_chart_mode ? 1000:((maximum+999)/1000)*1000;
    int minimum=(int)floor(low/100.0)*10,upper=(int)ceil(high/100.0)*10;
    lv_chart_set_axis_range(trend_chart,LV_CHART_AXIS_PRIMARY_Y,0,rpm_axis_max);
    lv_chart_set_axis_range(trend_chart,LV_CHART_AXIS_SECONDARY_Y,minimum*10,upper*10);
    char text[32];snprintf(text,sizeof text,thermal_chart_mode ? "%d%%":"%d",thermal_chart_mode ? 100:rpm_axis_max);set_text(trend_max,text);
    snprintf(text,sizeof text,thermal_chart_mode ? "%d%%":"%d",thermal_chart_mode ? 50:rpm_axis_max/2);set_text(trend_mid,text);
    for(int i=0;i<3;i++){snprintf(text,sizeof text,"%d",upper-i*(upper-minimum)/2);set_text(temperature_ticks[i],text);}
}

static const char *lookup_fields(const field_t *items, size_t count, const char *key) {
    for(size_t i = 0; i < count; i++)
        if(strcmp(items[i].key, key) == 0) return items[i].value;
    return "--";
}

static int source_uptime(const char *text, uint32_t *result) {
    char *end; unsigned long number = strtoul(text, &end, 10);
    if(end == text || number > 0xffffffffUL || (*end && strcmp(end, " ms"))) return 0;
    *result = (uint32_t)number; return 1;
}

static void read_npu_display(void) {
    /* Cache identity only. Every number, color and expiry still comes from a
       newly read, self-validated NPU publication with its original deadline. */
    static char selected_model[65], selected_context[512];
    nn_direct_used = 0;
    if(link_valid) {
        const char *model = value("panel_nn_model_sha256");
        const char *context = value("panel_collector_context");
        if(strcmp(value("panel_nn_present"), "1") || !strcmp(value("panel_model_valid"), "1") ||
           strlen(model) != 64 || strspn(model, "0123456789abcdef") != 64 ||
           !*context || !strcmp(context, "--") || strlen(context) >= sizeof(selected_context)) {
            *selected_model = *selected_context = 0; return;
        }
        snprintf(selected_model, sizeof(selected_model), "%s", model);
        snprintf(selected_context, sizeof(selected_context), "%s", context);
    }
    if(!*selected_model || !*selected_context) return;
    const char *path = "/run/cabinet-normal-npu/state.display.txt";
    static char boot[80];
#ifdef CABINET_HEADLESS
    if(getenv("CABINET_NPU_DISPLAY_PATH")) path = getenv("CABINET_NPU_DISPLAY_PATH");
    if(getenv("CABINET_NPU_BOOT_ID")) snprintf(boot, sizeof(boot), "%s", getenv("CABINET_NPU_BOOT_ID"));
#endif
    if(!*boot) {
        FILE *file = fopen("/proc/sys/kernel/random/boot_id", "r");
        if(!file) return;
        if(!fgets(boot, sizeof(boot), file)) *boot = 0;
        fclose(file); boot[strcspn(boot, "\r\n")] = 0;
    }
    if(!*boot) return;
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if(fd < 0) return;
    struct stat metadata;
    if(fstat(fd, &metadata) || !S_ISREG(metadata.st_mode) || metadata.st_uid != geteuid() ||
       (metadata.st_mode & 0022) || metadata.st_size > 65536) { close(fd); return; }
    FILE *stream = fdopen(fd, "r");
    if(!stream) { close(fd); return; }
    field_t incoming[96]; size_t count = 0; char line[600];
    while(count < 96 && fgets(line, sizeof(line), stream)) {
        char *separator = strchr(line, '=');
        if(!separator || (size_t)(separator - line) >= sizeof(incoming[0].key)) continue;
        *separator++ = 0; separator[strcspn(separator, "\r\n")] = 0;
        snprintf(incoming[count].key, sizeof(incoming[0].key), "%s", line);
        snprintf(incoming[count].value, sizeof(incoming[0].value), "%s", separator);
        count++;
    }
    fclose(stream);
    if(strcmp(lookup_fields(incoming, count, "display_schema"), "cabinet-normal-display-v2") ||
       strcmp(lookup_fields(incoming, count, "display_os_boot"), boot) ||
       strcmp(lookup_fields(incoming, count, "panel_nn_model_sha256"), selected_model)) return;
    if(strcmp(lookup_fields(incoming, count, "panel_nn_valid"), "1") == 0) {
        uint32_t direct_uptime, global_uptime;
        if(strcmp(lookup_fields(incoming, count, "display_collector_context"), selected_context) ||
           !source_uptime(lookup_fields(incoming, count, "display_status_uptime_ms"), &direct_uptime)) return;
        int newer = source_uptime(value("uptime"), &global_uptime) &&
                    (uint32_t)(direct_uptime-global_uptime) > 0 &&
                    (uint32_t)(direct_uptime-global_uptime) < 0x80000000U;
        if(link_valid && !newer) {
            const char *reason = value("panel_nn_reason");
            int timing_join = !*reason || !strcmp(reason,"--") || !strcmp(reason,"RESULT_EXPIRED") ||
                              !strcmp(reason,"FRAME_STALE") || !strcmp(reason,"REFERENCE_RESULT_WINDOW_INVALID");
            /* A newer global sensor/protection failure wins. A newer NPU
               source has already passed its own full window and control gate.
               Five-second display-average readiness is not NPU input validity. */
            if(strcmp(value("ui_rpm_valid"),"1") || strcmp(value("ui_current_valid"),"1") ||
               strcmp(value("core_temperature_valid"),"1") || strcmp(value("ui_pressure_valid"),"1") ||
               strcmp(value("panel_raw_features_valid"),"1") || !environment_current("panel_raw_features_deadline_ms") ||
               !timing_join) return;
        }
    }
    for(size_t i = 0; i < count; i++) {
        if(strncmp(incoming[i].key, "panel_nn_", 9) && strncmp(incoming[i].key, "panel_ref_", 10)) continue;
        size_t slot;
        for(slot = 0; slot < field_count; slot++) if(strcmp(fields[slot].key, incoming[i].key) == 0) break;
        if(slot == field_count) { if(field_count == 512) continue; field_count++; }
        fields[slot] = incoming[i];
    }
    nn_direct_used = 1;
}

static void publish_display_health(int nn_present, int nn_valid) {
#ifndef CABINET_HEADLESS
    static uint64_t written;
    static int previous_valid = -1;
    static char previous_count[40];
    uint64_t now = milliseconds();
    if(previous_valid == nn_valid && strcmp(previous_count, value("panel_nn_count")) == 0 && now - written < 1000) return;
    FILE *stream = fopen("/run/cabinet-live/hmi-status.txt.next", "w");
    if(!stream) return;
    fprintf(stream, "updated_ms=%llu\nlink_valid=%d\nnn_present=%d\nnn_valid=%d\nnn_direct=%d\nnn_count=%s\nnn_deadline_ms=%s\n",
            (unsigned long long)now, link_valid, nn_present, nn_valid, nn_direct_used, value("panel_nn_count"), value("panel_nn_deadline_ms"));
    if(fclose(stream) == 0 && rename("/run/cabinet-live/hmi-status.txt.next", "/run/cabinet-live/hmi-status.txt") == 0) {
        previous_valid = nn_valid; written = now;
        snprintf(previous_count, sizeof(previous_count), "%s", value("panel_nn_count"));
    }
#else
    (void)nn_present; (void)nn_valid;
#endif
}

static void read_fields(void) {
    field_count = 0;
    int file_current = 0;
    FILE *stream = fopen(state_path, "r");
    if(stream) {
        struct stat metadata;
        struct timespec wall;
        if(fstat(fileno(stream), &metadata) == 0 && clock_gettime(CLOCK_REALTIME, &wall) == 0) {
#ifdef __APPLE__
            struct timespec modified = metadata.st_mtimespec;
#else
            struct timespec modified = metadata.st_mtim;
#endif
            int64_t age = (int64_t)(wall.tv_sec - modified.tv_sec) * 1000 + (wall.tv_nsec - modified.tv_nsec) / 1000000;
            file_current = age >= 0 && age <= 2000;
        }
        char line[600];
        while(field_count < 512 && fgets(line, sizeof(line), stream)) {
            char *separator = strchr(line, '=');
            if(!separator || (size_t)(separator - line) >= sizeof(fields[0].key)) continue;
            *separator++ = 0;
            separator[strcspn(separator, "\r\n")] = 0;
            snprintf(fields[field_count].key, sizeof(fields[0].key), "%s", line);
            snprintf(fields[field_count].value, sizeof(fields[0].value), "%s", separator);
            field_count++;
        }
        fclose(stream);
    }
    uint64_t now = milliseconds();
    const char *sequence = value("sequence");
    if(strcmp(sequence, previous_sequence) != 0) {
        snprintf(previous_sequence, sizeof(previous_sequence), "%s", sequence);
        sequence_progress = now;
    }
    interface_mismatch = strcmp(value("panel_schema"), "--") != 0 && strcmp(value("panel_schema"), "industrial-v2") != 0;
    link_valid = file_current && strcmp(sequence, "--") && now - sequence_progress <= 2000 &&
                 strcmp(value("link"), "FCB1 + EDG1 ABI OK") == 0 && strcmp(value("panel_schema"), "industrial-v2") == 0;
    read_npu_display();
}

static void format_pressure(char *text, size_t size, double pressure_pa) {
    // Keep meaningful decimals within the shared fixed-width number column.
    int precision = fabs(pressure_pa) >= 99.995 ? 1 : fabs(pressure_pa) >= 9.9995 ? 2 : 3;
    if(fabs(pressure_pa) < 0.0005) pressure_pa = 0;
    snprintf(text, size, "%+.*f", precision, pressure_pa);
}

static void update_metrics(void) {
    const char *values[4] = {"daily_rpm_value", "core_temperature_c", "daily_current_value", "daily_pressure_value"};
    const char *validity[4] = {"daily_rpm_valid", "core_temperature_valid", "daily_current_valid", "daily_pressure_valid"};
    const char *units[4] = {"daily_rpm_unit", "", "daily_current_unit", "daily_pressure_unit"};
    for(int index = 0; index < 4; index++) {
        char text[180];
        int valid = link_valid && strcmp(value(validity[index]), "1") == 0;
        int overflow = 0;
        double measured = 0, target = 0;
        valid = valid && numeric(values[index], &measured);
        if(index == 1) valid = valid && strcmp(value("core_temperature_source"), "DS18B20/S4b") == 0 && measured >= -55 && measured <= 125;
        if(valid && index == 3) format_pressure(text, sizeof(text), measured);
        else if(valid) snprintf(text, sizeof(text), index == 0 ? "%.0f" : index == 2 ? "%.3f" : "%.1f", measured);
        else snprintf(text, sizeof(text), "--");
        set_text(metrics[index].value, text);
        uint32_t color = valid ? (index == 1 ? AMBER : TEAL) : MUTED;
        set_text_color(metrics[index].value, lv_color_hex(color), 0);
        set_text_color(metrics[index].unit, lv_color_hex(color), 0);

        const char *unit = index == 1 ? "℃" : value(units[index]);
        if(index == 0 && valid) unit = "RPM";
        if(index == 3 && valid && strcmp(unit, "kPa") == 0) {
            format_pressure(text, sizeof(text), measured * 1000);
            set_text(metrics[index].value, text);
            unit = "Pa";
        }
        if(valid && strcmp(unit, "原始码") == 0) {
            snprintf(text, sizeof(text), "%.0f", measured);
            set_text(metrics[index].value, text);
        }
        if(index == 2) {
            const char *kind = value("daily_current_kind");
            int raw = strcmp(unit, "原始码") == 0;
            set_text(metrics[index].title, raw ? (strcmp(kind, "raw_sample") == 0 ? "ADC CH1 原始码" : "ADC CH1 幅值") : "风机电流");
        }
        // All four primary values use one fixed font and the same alignment.
        lv_point_t extent;
        lv_text_get_size(&extent, lv_label_get_text(metrics[index].value), &lv_font_montserrat_44, 0, 0, 10000, LV_TEXT_FLAG_NONE);
        if(extent.x > 158) {
            overflow = 1;
            valid = 0;
            set_text(metrics[index].value, "--");
            set_text_color(metrics[index].value, lv_color_hex(MUTED), 0);
            set_text_color(metrics[index].unit, lv_color_hex(MUTED), 0);
        }
        set_text(metrics[index].unit, valid ? unit : "--");

        int target_valid = valid && index == 0 && numeric("daily_target", &target) && target > 0;
        if(overflow) {
            snprintf(text, sizeof(text), "数值超出显示范围");
        } else if(!valid) {
            snprintf(text, sizeof(text), "不显示旧值或推测值");
        } else if(strcmp(unit, "原始码") == 0) {
            snprintf(text, sizeof(text), index == 2 ? "电流单位待标定" : "压差单位待标定");
        } else if(target_valid) {
            snprintf(text, sizeof(text), "目标 %.0f | PWM %s", target, value("panel_pwm"));
        } else if(index == 1) {
            snprintf(text, sizeof(text), "DS18B20 · 核心器件");
        } else if(index == 2) {
            snprintf(text, sizeof(text), "%s", strcmp(value("daily_current_kind"), "nominal") == 0 ? "ACS712 · 参考值" : "AD7606 · 电流");
        } else if(index == 3) {
            snprintf(text, sizeof(text), "%s", strcmp(value("panel_sample_mode"), "2") == 0 ? "SDP810 · 风道压差" :
                     strcmp(value("panel_sample_mode"), "1") == 0 ? "AD7606 · 风道压差" : "来源未确认");
        } else {
            snprintf(text, sizeof(text), "真实观测");
        }
        set_text(metrics[index].note, text);
        if(metrics[index].bar) {
            int scaled = index == 0 ? target_valid : valid && strcmp(value("panel_sample_mode"), "2") == 0 && strcmp(unit, "Pa") == 0;
            double fraction = index == 0 ? (target_valid ? measured / target : 0) : fabs(measured) / 0.50;
            bar_value(metrics[index].bar, fraction, scaled, TEAL);
        }
    }
}

static void update_features(void) {
    int valid = link_valid && strcmp(value("panel_vibration_valid"), "1") == 0 &&
                environment_current("panel_raw_features_deadline_ms");
    int raw_valid = link_valid && !valid && strcmp(value("panel_raw_features_valid"), "1") == 0 &&
                    environment_current("panel_raw_features_deadline_ms");
    set_text(matrix_title,raw_valid ? "振动实测 · 原始码 / 单位待标定" : "双测点时域特征矩阵 (18维)");
    set_text(matrix_headers[0],raw_valid ? "RMS (code)" : "RMS (g)");
    set_text(matrix_headers[1],raw_valid ? "P-P (code)" : "P-P (g)");
    if(!valid && !raw_valid && strcmp(value("panel_icm_schema"), "ICM1_RAW_V1") == 0) {
        lv_obj_remove_flag(icm_raw_panel, LV_OBJ_FLAG_HIDDEN);
        for(int point = 0; point < 2; point++) {
            char deadline[48], raw_key[48], info_key[48];
            snprintf(deadline, sizeof(deadline), "panel_icm_%c_deadline_ms", point ? 'b' : 'a');
            snprintf(raw_key, sizeof(raw_key), "panel_icm_%c_raw", point ? 'b' : 'a');
            snprintf(info_key, sizeof(info_key), "panel_icm_%c_info", point ? 'b' : 'a');
            int current = environment_current(deadline);
            set_text(icm_raw_lines[point], current ? value(raw_key) : point ? "B XYZ: --  --  --" : "A XYZ: --  --  --");
            set_text(icm_raw_info[point], current ? value(info_key) : link_valid ? "NO FRESH VALID SAMPLE" : "LINK OFFLINE");
        }
    } else lv_obj_add_flag(icm_raw_panel, LV_OBJ_FLAG_HIDDEN);
    const char *kinds[3] = {"rms", "pp", "kurt"};
    for(int row = 0; row < 6; row++) for(int column = 0; column < 3; column++) {
        char key[64], text[32];
        double measured = 0;
        snprintf(key, sizeof(key), "%s%s_%c_%c",raw_valid ? "raw_feature_" : "daily_", kinds[column], row < 3 ? 'a' : 'b', "xyz"[row % 3]);
        if((valid || raw_valid) && numeric(key, &measured)) snprintf(text, sizeof(text), column == 2 ? "%.2f" : raw_valid ? "%.1f" : "%.3f", measured);
        else snprintf(text, sizeof(text), "--");
        set_text(matrix[row][column], text);
    }
    char text[160];
    if(raw_valid) snprintf(text, sizeof(text), "A/B 径向比 %s · 模型输入 %s%s",
        value("raw_feature_ratio_measured"), value("raw_feature_ratio_ab"),
        strcmp(value("raw_feature_ratio_clamped"), "1") == 0 ? " (限幅)" : "");
    else snprintf(text, sizeof(text), "A/B 径向比 -- · 模型输入 %s", valid ? value("daily_ratio_ab") : "--");
    set_text(ratio_label, text);

    int complete = valid || raw_valid;
    double bands[2][8] = {{0}};
    for(int point = 0; point < 2; point++) for(int band = 0; band < 8; band++) {
        char key[64];
        snprintf(key, sizeof(key), "%sband%c%d",raw_valid ? "raw_feature_" : "daily_", point ? 'b' : 'a', band);
        if(!numeric(key, &bands[point][band]) || bands[point][band] < 0 || bands[point][band] > 100) complete = 0;
    }
    for(int point = 0; point < 2; point++) for(int band = 0; band < 8; band++)
        lv_chart_set_series_value_by_id(band_chart, band_series[point], (uint32_t)band,
                                       complete ? (int32_t)lround(bands[point][band] * 10) : LV_CHART_POINT_NONE);
    for(int band = 0; band < 8; band++) {
        char key[48], hz_text[64];
        snprintf(key, sizeof(key), "%sband%d_hz",raw_valid ? "raw_feature_" : "panel_", band);
        if(valid || raw_valid) snprintf(hz_text, sizeof(hz_text), "%sHz", value(key));
        else snprintf(hz_text, sizeof(hz_text), "--");
        set_text(band_labels[band], hz_text);
    }
    if(complete) lv_obj_add_flag(band_empty, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_remove_flag(band_empty, LV_OBJ_FLAG_HIDDEN);
}

static const char *thermal_caption(void);
static const char *monitor_alert_caption(void);

static void update_decisions(void) {
    const char *channels[6] = {"oc", "ot", "stall", "os", "vib", "sensor"};
    int thermal = link_valid && strcmp(value("panel_temperature_pwm_present"),"1")==0 &&
        environment_current("panel_temperature_pwm_deadline_ms");
    int thermal_running = thermal && strcmp(value("panel_temperature_pwm_enabled"),"1")==0;
    const char *thermal_faults=value("panel_temperature_pwm_faults");
    set_text(pl_titles[1],thermal ? "温控":"过热");
    set_text(pl_titles[0],thermal ? "电流":"过流");
    int any_fault = 0, any_alarm = 0, any_unknown = 0;
    for(int index = 0; index < 6; index++) {
        char key[64];
        snprintf(key, sizeof(key), "panel_pl_%s", channels[index]);
        const char *state = link_valid ? value(key) : "UNKNOWN";
        int vibration_current = index == 4 && !strcmp(value("panel_vibration_monitor_enabled"), "1") &&
            environment_current("panel_vibration_monitor_deadline_ms");
        if(index >= 4 && (strcmp(state, "CLEAR") == 0 || strcmp(state, "UNREADY") == 0) &&
           !vibration_current && !environment_current("panel_raw_features_deadline_ms")) state = "UNKNOWN";
        if(thermal && index<5 && strcmp(state,"ALARM") && strcmp(state,"LATCH") && strcmp(state,"WARN")) {
            int thermal_alarm=(index==0 && (strstr(thermal_faults,"CURRENT_") || strstr(thermal_faults,"ADC_INVALID"))) ||
                (index==1 && (strstr(thermal_faults,"TEMPERATURE_INVALID") || strstr(thermal_faults,"OVER_TEMPERATURE"))) ||
                (index==2 && strstr(thermal_faults,"FG_MISSING")) || (index==3 && strstr(thermal_faults,"OVERSPEED"));
            if(thermal_alarm)state="ALARM";
            else if(index<4 && thermal_running){
                int input_valid=index==0 ? !strcmp(value("daily_current_valid"),"1") :
                    index==1 ? !strcmp(value("core_temperature_valid"),"1") &&
                               !strcmp(value("panel_temperature_pwm_target_valid"),"1") :
                    index==2 ? !strcmp(value("daily_rpm_valid"),"1") : 1;
                state=index<3 ? (input_valid ? "CLEAR":"UNKNOWN") : "REFERENCE";
            }
        }
        if(index==3 && thermal && strcmp(value("panel_speed_present"),"1")==0 &&
           strcmp(state,"LATCH") && !(strcmp(state,"ALARM")==0 && !strstr(thermal_faults,"OVERSPEED"))) {
            const char *speed=value("panel_speed_state");
            if(!strcmp(speed,"ALARM")){state="ALARM";}
            else if(!strcmp(speed,"WARNING")){state="WARN";}
            else if(!strcmp(speed,"NORMAL") || !strcmp(speed,"PENDING")) {
                state="CLEAR";
            } else {state="UNKNOWN";}
        }
        int state_alarm = !strcmp(state, "ALARM") || !strcmp(state, "LATCH");
        int state_normal = !strcmp(state, "CLEAR") || !strcmp(state, "REFERENCE");
        /* Missing or unconfigured input is a warning, never a healthy value. */
        uint32_t color = state_alarm ? RED : state_normal ? GREEN : AMBER;
        const char *caption = state_alarm ? "报警" : state_normal ? "正常" : "预警";
        uint32_t border = color == GREEN ? 0x1e4d3b : color == AMBER ? 0x6b5125 : color == RED ? 0x7a272c : EDGE;
        if(color == RED || color == AMBER) any_fault = 1;
        if(color == RED) any_alarm = 1;
        if(!state_alarm && !state_normal && strcmp(state, "WARN")) any_unknown = 1;
        set_border_color(pl_boxes[index], lv_color_hex(border), 0);
        if(index < 5) {
            for(int dot = 0; dot < 9; dot++)
                set_bg_color(pl_lights[index][dot], lv_color_hex(color), 0);
            set_text(pl_state_labels[index], caption);
            set_text_color(pl_state_labels[index], lv_color_hex(color == 0x2c3742 ? MUTED : color), 0);
        } else {
            set_bg_color(pl_sensor_dot, lv_color_hex(color), 0);
            set_text(pl_sensor_label, caption);
            set_text_color(pl_sensor_label, lv_color_hex(color == 0x2c3742 ? MUTED : color), 0);
        }
    }
    char text[256];
    if(link_valid) {
        const char *scope = value("panel_protection_scope");
        const char *protection = strcmp(scope, "CONFIGURATION_REQUIRED") == 0 ? "保护阈值待配置" :
                                 strcmp(scope, "PARTIAL_CONFIGURATION_REQUIRED") == 0 ? "保护部分待配置" :
                                 strcmp(scope, "CONTROL_NOT_STARTED") == 0 ? "保护已配置 · 待投运" :
                                 strcmp(scope, "READY") == 0 ? "保护已就绪" : "保护状态待确认";
        const char *alert=thermal ? monitor_alert_caption():NULL;
        if(thermal)snprintf(text,sizeof(text),"%s",alert ? alert:thermal_caption());
        else snprintf(text, sizeof(text), "%s · %s",protection,value("panel_drive_status"));
        double thermal_level=0;
        numeric("panel_temperature_pwm_alarm_level",&thermal_level);
        set_text_color(pl_status_label, lv_color_hex((any_alarm || (thermal && thermal_level>=2)) ? RED :
                       (any_fault || (thermal && thermal_level>=1)) ? AMBER : any_unknown ? MUTED : GREEN), 0);
    } else {
        snprintf(text, sizeof(text), "Status: 驱动状态未知 | PI 未确认");
        set_text_color(pl_status_label, lv_color_hex(MUTED), 0);
    }
    set_text(pl_status_label, text);

    int nn_present = strcmp(value("panel_nn_present"), "1") == 0 && strcmp(value("panel_model_valid"), "1") != 0;
    double nn_score = 0, nn_latency = 0;
    int nn_valid = (link_valid || nn_direct_used) && strcmp(value("panel_nn_valid"), "1") == 0 &&
                   deadline_current("panel_nn_deadline_ms") &&
                   numeric("panel_nn_score", &nn_score) && nn_score >= 0 && nn_score <= 1000000 &&
                   numeric("panel_nn_latency_ms", &nn_latency) && nn_latency > 0 && nn_latency <= 200;
    publish_display_health(nn_present, nn_valid);
    const char *advisory = nn_valid && strcmp(value("panel_nn_advisory_valid"), "1") == 0 ?
                           value("panel_nn_advisory_state") : "UNKNOWN";
    int nn_outside = nn_valid && !strcmp(value("panel_nn_reference_eligible"), "0");
    int nn_warning = !nn_outside && (strcmp(advisory, "WARN") == 0 || strcmp(advisory, "RECOVERING") == 0);
    int nn_normal = !nn_outside && strcmp(advisory, "NORMAL") == 0;
    double pending_elapsed = 0, pending_required = 0;
    int nn_grace = !strcmp(advisory, "PENDING") &&
                   !strcmp(value("panel_nn_advisory_normal_latched"), "1") &&
                   numeric("panel_nn_advisory_elapsed_ms", &pending_elapsed) &&
                   numeric("panel_nn_advisory_required_ms", &pending_required) &&
                   pending_elapsed >= 0 && pending_elapsed < pending_required && pending_required <= 2000;
    /* Green during bounded observation means the last confirmed state is
       normal. Keep the live score and the explicit pending label visible. */
    uint32_t nn_color = nn_outside ? TEAL : nn_warning ? AMBER : (nn_normal || nn_grace) ? GREEN : MUTED;
    if(nn_present) {
        const char *scope = nn_valid ? "实推理" : strcmp(value("panel_nn_state"), "NATIVE_FAULT") == 0 ? "故障" : "等待输入";
        snprintf(text, sizeof(text), "第2层 · NPU正常基线 (%s)", scope);
        set_text(model_state, text);
        const char *groups[5] = {"a", "b", "current", "temperature", "airflow"};
        const char *names[5] = {"振动A", "振动B", "电流码", "温度", "风道/转速"};
        for(int index = 0; index < 5; index++) {
            char key[64]; double deviation = 0;
            snprintf(key, sizeof(key), "panel_nn_group_%s", groups[index]);
            int valid = nn_valid && numeric(key, &deviation) && deviation >= 0;
            if(valid) snprintf(text, sizeof(text), "%s %.2fx", names[index], deviation);
            else snprintf(text, sizeof(text), "%s --", names[index]);
            uint32_t color = valid ? nn_color : MUTED;
            set_text(probability_labels[index], text);
            set_text_color(probability_labels[index], lv_color_hex(color), 0);
            bar_value(probability_bars[index], valid ? deviation / 2.0 : 0, valid, color);
        }
        if(nn_outside) snprintf(text,sizeof(text),"工况超出基线 · 实推理 %sms",value("panel_nn_latency_ms"));
        else if(nn_valid) snprintf(text, sizeof(text), "%s · 重建%s | %sms",
            nn_warning ? (strcmp(advisory, "RECOVERING") == 0 ? "恢复确认" : "持续偏离") :
            nn_normal ? "匹配" : strcmp(advisory, "PENDING") == 0 ? "偏离待确认" : "等待确认",
            value("panel_nn_score"), value("panel_nn_latency_ms"));
        else if(strcmp(value("panel_nn_reason"),"OUTPUT_OUTSIDE_REFERENCE")==0 ||
                strcmp(value("panel_nn_reason"),"OPERATING_MODE_OUTSIDE_REFERENCE")==0)
            snprintf(text,sizeof(text),"当前PWM超出基线 · 待学习此工况");
        else snprintf(text, sizeof(text), "%s · 旧结果已清空",
            strcmp(value("panel_nn_state"), "STOPPED") == 0 ? "推理服务已停止" :
            strcmp(value("panel_nn_state"), "LOADING") == 0 ? "模型加载中" :
            strcmp(value("panel_nn_state"), "NATIVE_FAULT") == 0 ? "推理服务故障" :
            strcmp(value("panel_nn_reason"), "RESULT_EXPIRED") == 0 || strcmp(value("panel_nn_reason"), "FRAME_STALE") == 0 ? "等待新的推理结果" : "等待有效推理输入");
        set_text(model_note, text);
    } else {
    int model_valid = link_valid && strcmp(value("panel_model_valid"), "1") == 0 &&
        (strcmp(value("panel_classifier_present"), "1") != 0 ||
         environment_current("panel_classifier_deadline_ms"));
    snprintf(text, sizeof(text), "第2层 · 本地五分类推理 (%s)", model_valid ? value("panel_model_state") : "未就绪");
    set_text(model_state, text);
    set_text(model_note, model_valid ? value("panel_model_note") :
             strcmp(value("panel_classifier_present"), "1") == 0 ? "分类结果无效 · 检查模型与输入" :
             "五类样本按标签学习 · 异常只告警");
    const char *classes[5] = {"normal", "imbalance", "clog", "overheat", "stall"};
    const char *zh_classes[5] = {"正常", "失衡", "滤网堵塞", "过热", "卡死"};
    for(int index = 0; index < 5; index++) {
        char key[64];
        double probability = 0;
        snprintf(key, sizeof(key), "panel_prob_%s", classes[index]);
        int valid = model_valid && numeric(key, &probability) && probability >= 0 && probability <= 100;
        if(valid) snprintf(text, sizeof(text), "%s %.1f%%", zh_classes[index], probability);
        else snprintf(text, sizeof(text), "%s --", zh_classes[index]);
        set_text(probability_labels[index], text);
        set_text_color(probability_labels[index], lv_color_hex(valid ? (index == 0 ? GREEN : TEXT) : MUTED), 0);
        bar_value(probability_bars[index], valid ? probability / 100.0 : 0, valid, index == 0 ? GREEN : TEAL);
    }

    }

    double score = 0, limit = 0;
    int baseline_valid = link_valid && strcmp(value("panel_baseline_valid"), "1") == 0 && numeric("ui_learn_score", &score) &&
                         numeric("panel_baseline_limit", &limit) && limit > 0;
    if(nn_present && !baseline_valid) {
        int reference_valid = nn_valid && strcmp(value("panel_ref_valid"), "1") == 0 &&
                              deadline_current("panel_ref_deadline_ms") &&
                              numeric("panel_ref_score", &score) && score >= 0 && score <= 1000000;
        const char *groups[4] = {"amplitude", "spectrum", "ratio", "process"};
        double deviations[4] = {0};
        for(int index = 0; index < 4; index++) {
            char key[64]; snprintf(key, sizeof(key), "panel_ref_group_%s", groups[index]);
            if(!numeric(key, &deviations[index]) || deviations[index] < 0 || deviations[index] > 1000000) reference_valid = 0;
        }
        set_text(baseline_title, "第3层 · 实测样本范围对照");
        if(reference_valid) {
            snprintf(text, sizeof(text), "%s %.2fx / 1.00x · 输入范围",
                score <= 1 ? "范围内" : "超出范围", score);
            set_text(baseline_score, text);
            snprintf(text, sizeof(text), "%.2f", score); set_text(baseline_badge_label, text);
            lv_obj_set_pos(baseline_badge, 12 + (int)(fmin(0.85, fmax(0.08, score / 2)) * 290), 62);
            snprintf(text, sizeof(text), "%s窗训练 · %s段实测 · 样本对照",
                value("panel_nn_training_rows"), value("panel_ref_sessions"));
        } else {
            set_text(baseline_score, "输入范围 -- · 等待有效实时结果");
            set_text(baseline_badge_label, "--"); lv_obj_set_pos(baseline_badge, 12, 62);
            snprintf(text, sizeof(text), "只读样本对照 · 当前无有效结果");
        }
        set_text(baseline_scope, text);
        bar_value(baseline_bar, score / 2, reference_valid, nn_color);
        for(int index = 0; index < 4; index++) {
            if(reference_valid) snprintf(text, sizeof(text), "%.2fx", deviations[index]);
            else snprintf(text, sizeof(text), "--");
            uint32_t color = nn_color;
            set_text(group_values[index], text);
            set_text_color(group_values[index], lv_color_hex(reference_valid ? color : MUTED), 0);
            bar_value(group_bars[index], deviations[index] / 2, reference_valid, color);
        }
        return;
    }
    set_text(baseline_title, "第3层 · 工况健康基线");
    if(baseline_valid) {
        snprintf(text, sizeof(text), "偏离度 %.2f / %.2f (%s)", score, limit, value("ui_learn_evidence"));
        set_text(baseline_score, text);
        snprintf(text, sizeof(text), "%.2f", score);
        set_text(baseline_badge_label, text);
        double frac = score / limit;
        if(frac < 0.08) frac = 0.08;
        if(frac > 0.85) frac = 0.85;
        lv_obj_set_pos(baseline_badge, 12 + (int)(frac * 290), 62);
    } else {
        snprintf(text, sizeof(text), "偏离度 -- / -- (%s)", link_valid ? value("ui_learn_evidence") : "基线状态未知");
        set_text(baseline_score, text);
        set_text(baseline_badge_label, "--");
        lv_obj_set_pos(baseline_badge, 12, 62);
    }
    bar_value(baseline_bar, baseline_valid ? score / limit : 0, baseline_valid, score >= limit ? AMBER : TEAL);
    const char *groups[4] = {"amplitude", "spectrum", "ratio", "process"};
    for(int index = 0; index < 4; index++) {
        char key[64];
        double group = 0;
        snprintf(key, sizeof(key), "panel_group_%s", groups[index]);
        int valid = baseline_valid && numeric(key, &group) && group >= 0;
        set_text(group_values[index], valid ? value(key) : "--");
        bar_value(group_bars[index], valid ? group / limit : 0, valid, TEAL);
    }
    set_text(baseline_scope, link_valid && strstr(value("ui_learn_scope"), "观察") ? "网页双确认 · 观察模式" : "只读显示 · 学习由网页确认");
}

static int monitor_fault(const char *code) {
    const char *list=value("panel_temperature_pwm_faults"),*p=list;
    size_t len=strlen(code);
    while((p=strstr(p,code))!=NULL) {
        if((p==list || p[-1]==',') && (p[len]=='\0' || p[len]==','))return 1;
        p+=len;
    }
    return 0;
}

static const char *monitor_alert_caption(void) {
    static char text[192];
    const char *codes[]={"CURRENT_PEAK","OVER_TEMPERATURE","OVERSPEED","VIBRATION_HIGH",
        "TEMPERATURE_INVALID","ADC_INVALID","FG_MISSING","CURRENT_MEAN","OWNER_CONFLICT",
        "WATCHDOG_EXPIRED","CONTROL_READBACK_INVALID","NPU_STALL","NPU_OVERHEAT","NPU_CLOG",
        "NPU_IMBALANCE","VIBRATION_WARN","RPM_HIGH_SUSTAINED","NPU_DEVIATION","TEST_ALARM"};
    const char *labels[]={"电流峰值报警","温度过高报警","超速报警","振动报警",
        "温度输入异常","电流采集异常","FG测速丢失","电流过高报警","控制状态异常",
        "控制状态异常","控制读回异常","NPU卡死报警","NPU过热报警","NPU风道预警",
        "NPU振动预警","振动预警","高速预警","NPU基线偏离 · 预警","告警测试"};
    int first=-1,count=0;
    for(size_t i=0;i<sizeof(codes)/sizeof(codes[0]);i++) if(monitor_fault(codes[i])) {
        if(first<0)first=(int)i;
        count++;
    }
    if(first<0)return NULL;
    if(count>1)snprintf(text,sizeof(text),"%s +%d",labels[first],count-1);
    else snprintf(text,sizeof(text),"%s",labels[first]);
    return text;
}

static const char *thermal_caption(void) {
    const char *state=value("panel_temperature_pwm_state");
    if(strcmp(state,"RUNNING")==0)return "温度自动调速正常";
    if(strcmp(state,"DISABLED")==0)return "温度调速已停用";
    if(strcmp(state,"FIRMWARE_REQUIRED")==0)return "等待温控固件更新";
    if(strcmp(state,"WAITING_SENSOR")==0)return "等待有效温度";
    if(strcmp(state,"FAULT_LATCHED")==0)return "温控输出异常 · 请检查固件";
    if(strcmp(state,"STOPPED_UNSAVED")==0)return "已停用 · SD未保存";
    if(strcmp(state,"STOPPING")==0)return "等待实际输出归零";
    if(strcmp(state,"OWNER_CONFLICT")==0)return "另一控制模式正在运行";
    if(strcmp(state,"APPLY_FAILED")==0 || strcmp(state,"ARM_REJECTED")==0 || strcmp(state,"CONFIGURATION_REJECTED")==0)
        return "温控参数尚未应用";
    return "等待温控硬件读回";
}

static void update_thermal_trend(void) {
    uint64_t now=milliseconds(),bucket=now/1000*1000;
    double actual=0,target=0,temperature=0;
    int fresh=link_valid && environment_current("panel_temperature_pwm_deadline_ms");
    int av=fresh && strcmp(value("panel_control_pwm_valid"),"1")==0 &&
        numeric("panel_control_pwm_percent",&actual) && actual>=0 && actual<=100;
    int tv=fresh && strcmp(value("panel_temperature_pwm_target_valid"),"1")==0 &&
        numeric("panel_temperature_pwm_target_percent",&target) && target>=0 && target<=100;
    int cv=fresh && strcmp(value("core_temperature_valid"),"1")==0 &&
        strcmp(value("core_temperature_source"),"DS18B20/S4b")==0 &&
        numeric("core_temperature_c",&temperature) && temperature>=-55 && temperature<=125;
    char text[256],contract[256];
    if(av)snprintf(text,sizeof text,"实际 %.1f%%",actual);else snprintf(text,sizeof text,"实际 --%%");set_text(trend_values[0],text);
    if(tv)snprintf(text,sizeof text,"目标 %.1f%%",target);else snprintf(text,sizeof text,"目标 --%%");set_text(trend_values[1],text);
    if(cv)snprintf(text,sizeof text,"核心 %.1f℃",temperature);else snprintf(text,sizeof text,"核心 --℃");set_text(trend_values[2],text);
    set_text(control_tracking_note,fresh ? thermal_caption():"控制数据过期 · 等待更新");
    int fault=strcmp(value("panel_temperature_pwm_state"),"FAULT_LATCHED")==0;
    set_text_color(control_tracking_note,lv_color_hex(fault ? RED:(fresh && tv ? TEAL:MUTED)),0);
    snprintf(text,sizeof text,"%s℃→0%% / %s℃→100%%",value("panel_temperature_pwm_low_C"),value("panel_temperature_pwm_high_C"));
    set_text(control_pwm_note,text);
    snprintf(contract,sizeof contract,"TPW/%s/%s/%s",value("panel_source"),value("panel_control_identity"),value("panel_temperature_pwm_revision"));
    if(strcmp(contract,previous_contract)!=0){clear_trend();snprintf(previous_contract,sizeof previous_contract,"%s",contract);}
    if(!fresh){clear_trend();last_plot=bucket;trend_ranges();return;}
    if(!last_plot)last_plot=bucket>=1000?bucket-1000:0;
    if(bucket<=last_plot)return;
    uint64_t slots=(bucket-last_plot)/1000;if(slots>61)slots=61;
    for(uint64_t i=1;i<slots;i++)trend_point(LV_CHART_POINT_NONE,LV_CHART_POINT_NONE,LV_CHART_POINT_NONE);
    int unique=strcmp(previous_plot_sequence,value("sequence"))!=0;
    trend_point(av && unique?(int32_t)lround(actual*10):LV_CHART_POINT_NONE,
                tv && unique?(int32_t)lround(target*10):LV_CHART_POINT_NONE,
                cv && unique?(int32_t)lround(temperature*10):LV_CHART_POINT_NONE);
    if(av || tv || cv)lv_obj_add_flag(trend_empty,LV_OBJ_FLAG_HIDDEN);
    trend_ranges();snprintf(previous_plot_sequence,sizeof previous_plot_sequence,"%s",value("sequence"));last_plot=bucket;
}

static void update_trend(void) {
    int thermal=strcmp(value("panel_temperature_pwm_present"),"1")==0;
    if(thermal!=thermal_chart_mode){clear_trend();previous_contract[0]='\0';thermal_chart_mode=thermal;}
    set_text(trend_title,thermal ? "PWM / 核心温度 · 60s":"转速 / 核心温度 · 60s");
    set_text(trend_unit,thermal ? "PWM":"RPM");
    if(thermal){update_thermal_trend();return;}
    uint64_t now=milliseconds(),bucket=now/1000*1000;
    double rpm=0,temperature=0,target=0,error=0,pwm=0;
    int rpm_valid=link_valid && strcmp(value("daily_rpm_valid"),"1")==0 && numeric("daily_rpm_value",&rpm) && rpm>=0 && rpm<=65535;
    int temperature_valid=link_valid && strcmp(value("core_temperature_valid"),"1")==0 &&
        strcmp(value("core_temperature_source"),"DS18B20/S4b")==0 && numeric("core_temperature_c",&temperature) && temperature>=-55 && temperature<=125;
    int enabled=link_valid && strcmp(value("panel_control_enabled"),"1")==0;
    int control_current=link_valid && environment_current("panel_control_deadline_ms");
    int target_valid=enabled && control_current && strcmp(value("panel_control_target_valid"),"1")==0 &&
        numeric("panel_control_target_rpm",&target) && target>0 && target<=32767;
    int pwm_valid=control_current && strcmp(value("panel_control_pwm_valid"),"1")==0 &&
        numeric("panel_control_pwm_percent",&pwm) && pwm>=0 && pwm<=100;
    int settled=target_valid && rpm_valid && strcmp(value("panel_control_settled"),"1")==0;
    char text[256],contract[256];
    if(rpm_valid)snprintf(text,sizeof text,"实测 %.0f",rpm);else snprintf(text,sizeof text,"实测 --");set_text(trend_values[0],text);
    if(target_valid)snprintf(text,sizeof text,"目标 %.0f",target);else snprintf(text,sizeof text,"目标 --");set_text(trend_values[1],text);
    if(temperature_valid)snprintf(text,sizeof text,"核心 %.1f℃",temperature);else snprintf(text,sizeof text,"核心 --℃");set_text(trend_values[2],text);
    if(!link_valid)snprintf(text,sizeof text,"采集失效 · 等待有效数据");
    else if(control_current && strcmp(value("panel_control_state"),"BENCH_OPEN_LOOP")==0)snprintf(text,sizeof text,"开环调速 · 闭环未启用");
    else if(!enabled) snprintf(text,sizeof text,"%s",strcmp(value("panel_control_state"),"CONFIGURATION_RESTORE_REQUIRED")==0?"参数未恢复 · 等待加载":"闭环未启用 · 仅采集");
    else if(!control_current) snprintf(text,sizeof text,"控制数据过期 · 目标已隐藏");
    else if(!target_valid) snprintf(text,sizeof text,"等待控制读回 · 目标未确认");
    else if(settled) snprintf(text,sizeof text,"连续10s达标 · 最大误差 %s%%",value("panel_control_10s_error_pct"));
    else snprintf(text,sizeof text,"%s · 目标 %.0f RPM",strcmp(value("panel_control_phase"),"STARTING")==0?"启动跟踪":"PI跟踪",target);
    set_text(control_tracking_note,text);
    set_text_color(control_tracking_note,lv_color_hex(settled?GREEN:MUTED),0);
    char duty[32],difference[40];
    if(pwm_valid)snprintf(duty,sizeof duty,"%.1f",pwm);else snprintf(duty,sizeof duty,"--");
    if(target_valid && rpm_valid && numeric("panel_control_error_rpm",&error))snprintf(difference,sizeof difference,"%+.0f RPM",error);
    else snprintf(difference,sizeof difference,"--");
    snprintf(text,sizeof text,"PWM %s%% · 转速误差 %s",duty,difference);set_text(control_pwm_note,text);
    snprintf(contract,sizeof contract,"%s/%s/%s/%d/%s",value("panel_source"),value("panel_sample_mode"),value("ui_configuration"),enabled,value("panel_control_identity"));
    if(strcmp(contract,previous_contract)!=0) {
        clear_trend();snprintf(previous_contract,sizeof previous_contract,"%s",contract);
    }
    if(!link_valid) {clear_trend();last_plot=bucket;trend_ranges();return;}
    if(!last_plot)last_plot=bucket>=1000?bucket-1000:0;
    if(bucket<=last_plot)return;
    uint64_t slots=(bucket-last_plot)/1000;
    if(slots>61)slots=61;
    /* Missed wall-clock seconds and duplicate collector samples stay blank.
       Every curve advances on the same one-second clock, without interpolation. */
    for(uint64_t i=1;i<slots;i++)trend_point(LV_CHART_POINT_NONE,LV_CHART_POINT_NONE,LV_CHART_POINT_NONE);
    int fresh_sequence=strcmp(previous_plot_sequence,value("sequence"))!=0;
    trend_point(rpm_valid && fresh_sequence?(int32_t)lround(rpm):LV_CHART_POINT_NONE,
                target_valid && fresh_sequence?(int32_t)lround(target):LV_CHART_POINT_NONE,
                temperature_valid && fresh_sequence?(int32_t)lround(temperature*10):LV_CHART_POINT_NONE);
    if(rpm_valid || temperature_valid || target_valid)lv_obj_add_flag(trend_empty,LV_OBJ_FLAG_HIDDEN);
    trend_ranges();
    snprintf(previous_plot_sequence,sizeof previous_plot_sequence,"%s",value("sequence"));last_plot=bucket;
}

static int read_life_display(void) {
    const char *path = "/run/cabinet-fan-life/state.display.txt";
    static char boot[80];
#ifdef CABINET_HEADLESS
    if(getenv("CABINET_LIFE_DISPLAY_PATH")) path = getenv("CABINET_LIFE_DISPLAY_PATH");
    if(getenv("CABINET_LIFE_BOOT_ID")) snprintf(boot, sizeof boot, "%s", getenv("CABINET_LIFE_BOOT_ID"));
#endif
    if(!*boot) {
        FILE *f = fopen("/proc/sys/kernel/random/boot_id", "r");
        if(!f) return 0;
        if(!fgets(boot, sizeof boot, f)) *boot = 0;
        fclose(f); boot[strcspn(boot,"\r\n")] = 0;
    }
    if(!*boot) return 0;
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if(fd < 0) return 0;
    struct stat st;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || (st.st_mode & 0022) || st.st_size>8192) { close(fd); return 0; }
    FILE *f = fdopen(fd,"r");
    if(!f) { close(fd); return 0; }
    field_t incoming[32]; size_t count=0; char line[600];
    while(count<32 && fgets(line,sizeof line,f)) {
        char *sep=strchr(line,'=');
        if(!sep || (size_t)(sep-line)>=sizeof incoming[0].key) continue;
        *sep++=0; sep[strcspn(sep,"\r\n")]=0;
        snprintf(incoming[count].key,sizeof incoming[0].key,"%s",line);
        snprintf(incoming[count].value,sizeof incoming[0].value,"%s",sep); count++;
    }
    fclose(f);
    if(strcmp(lookup_fields(incoming,count,"display_schema"),"cabinet-life-display-v1") || strcmp(lookup_fields(incoming,count,"display_os_boot"),boot)) return 0;
    for(size_t i=0;i<count;i++) {
        if(strncmp(incoming[i].key,"panel_life_",11)) continue;
        size_t slot;
        for(slot=0;slot<field_count;slot++) if(!strcmp(fields[slot].key,incoming[i].key)) break;
        if(slot==field_count) { if(field_count==512) continue; field_count++; }
        fields[slot]=incoming[i];
    }
    double deadline;
    return numeric("panel_life_deadline_ms",&deadline) && deadline>=milliseconds() && deadline-milliseconds()<=5000;
}

static void update_life(void) {
    double hours=0,nominal=0;
    int available=read_life_display() && !strcmp(value("panel_life_available"),"1") && numeric("panel_life_hours",&hours) && numeric("panel_life_nominal_hours",&nominal) && hours>=0 && nominal>0;
    int ready=available && !strcmp(value("panel_life_kind"),"DECLARED_LIFE_AND_FULL_SPEED_CURVE");
    char text[160];
    if(available) snprintf(text,sizeof text,hours>=100000?"%.0f":"%.1f",hours); else snprintf(text,sizeof text,"--");
    set_text(life_hours,text);
    uint32_t color=ready && hours<=0 ? AMBER:TEAL;
    set_text_color(life_hours,lv_color_hex(available?color:MUTED),0);
    set_text(life_caption,!available?"寿命采集未连接 · 保留SD记录":!ready?"初始设定 · 待满速基准":strcmp(value("panel_life_source_valid"),"1")?"最近估算 · 当前采样不可用":hours<=0?"已到设定维护终点":"工时与满速衰减 · 经验估算");
    bar_value(life_bar,available?hours/nominal:0,available,color);
    snprintf(text,sizeof text,"基准 %s · 复测 %s RPM",available?value("panel_life_reference_rpm"):"--",available?value("panel_life_latest_rpm"):"--");set_text(life_rpm,text);
    snprintf(text,sizeof text,"衰减 %s%% · 工时 %s h",available?value("panel_life_loss"):"--",available?value("panel_life_operating_hours"):"--");set_text(life_detail,text);
    if(available) snprintf(text,sizeof text,"SD保存 · %s次满速 · 终点%s%%",value("panel_life_points"),value("panel_life_endpoint_loss"));
    else snprintf(text,sizeof text,"等待寿命服务恢复");
    set_text(life_note,text);
}

static void refresh_inference(lv_timer_t *timer) {
    (void)timer;
    /* Inference arrives independently of the 200 ms whole-dashboard update.
       Read its original deadline at 50 ms; never extend or recycle a result. */
    read_fields();
    update_decisions();
}

static void refresh(lv_timer_t *timer) {
    (void)timer;
    read_fields();
    char text[512];
    uint32_t color = !link_valid ? RED : strcmp(value("ui_severity"), "0") == 0 ? GREEN : strcmp(value("ui_severity"), "3") == 0 ? RED : strcmp(value("ui_severity"), "1") == 0 ? MUTED : AMBER;
    uint32_t bg = color == GREEN ? 0x0f2922 : color == AMBER ? 0x2c2212 : color == MUTED ? 0x18212b : 0x2d1418;
    if(link_valid && strcmp(value("ui_severity"), "0") == 0) {
        snprintf(text, sizeof(text), "%s · L%s", value("ui_banner_title"), value("panel_level"));
    } else if(link_valid) {
        snprintf(text, sizeof(text), "%s · L%s", value("ui_banner_title"), value("panel_level"));
    } else {
        snprintf(text, sizeof(text), "%s", interface_mismatch ? "[ 显示接口版本不匹配 ]" : "[ OFFLINE · 硬件数据读取失效 ]");
    }
    if(link_valid && strcmp(value("panel_temperature_pwm_present"),"1")==0 && environment_current("panel_temperature_pwm_deadline_ms")) {
        const char *alert=monitor_alert_caption();
        double level=0,hardware_level=0;
        numeric("panel_temperature_pwm_alarm_level",&level);numeric("panel_level",&hardware_level);
        if(alert && !(color==RED && hardware_level>level)) {
            snprintf(text,sizeof text,"%s",alert);
            color=level>=2 ? RED:AMBER;
        } else if(color!=RED && color!=AMBER) {
            snprintf(text,sizeof text,"%s",thermal_caption());
            color=strcmp(value("panel_temperature_pwm_state"),"RUNNING")==0 ? GREEN:
                  strcmp(value("panel_temperature_pwm_state"),"FAULT_LATCHED")==0 ? RED:MUTED;
        }
        bg=color==RED ? 0x2d1418:color==AMBER ? 0x2c2212:color==GREEN ? 0x0f2922:0x18212b;
    }
    set_text(banner_title, text);
    set_text_color(banner_title, lv_color_hex(color), 0);
    set_border_color(banner, lv_color_hex(color), 0);
    set_bg_color(banner, lv_color_hex(bg), 0);

    snprintf(text, sizeof(text), "风冷边缘智能监控 | %s · %s",
             link_valid ? value("panel_source") : "WAIT",
             link_valid && strcmp(value("panel_sample_mode"), "2") == 0 ? "SDP810" : link_valid && strcmp(value("panel_sample_mode"), "1") == 0 ? "ADC差压" : "等待采样");
    set_text(title_label, text);

    snprintf(text, sizeof(text), "%s | Fs %s/%s Hz | 帧 #%s | %s",
             link_valid ? "FCB1/EDG1 在线" : "FCB1/EDG1 未确认",
             link_valid ? value("daily_frame_rate_a") : "--",
             link_valid ? value("daily_frame_rate_b") : "--",
             link_valid ? value("frame_id") : "--",
             link_valid ? value("ui_runtime") : "--:--:--");
    set_text(header_meta_label, text);

    update_metrics();
    update_features();
    update_decisions();
    update_trend();
    update_life();
    int aht_current = environment_current("environment_aht_deadline_ms") && strcmp(value("inlet_source"), "AHT20") == 0;
    snprintf(text, sizeof(text), "进风 %s℃ · RH %s%% | AHT20", aht_current ? value("inlet_temperature_c") : "--",
             aht_current ? value("relative_humidity_pct") : "--");
    set_text(inlet_label, text);
    snprintf(text, sizeof(text), "%s%s", preview_mode ? "UI预览 / 合成数据 / 不连接硬件 · " : "", link_valid ? value("daily_notice") : interface_mismatch ? "请同步采集服务与显示程序 · 不使用旧接口数据" : "采集失效 · 不使用旧值 · 温度调速不依赖显示");
    set_text(footer, text);
#ifdef CABINET_RECORDING
    refresh_capture();
#endif
    operator_refresh();
}

#ifdef CABINET_HEADLESS
static uint8_t pixels[WIDTH * HEIGHT * 3];
static void capture_flush(lv_display_t *display, const lv_area_t *area, uint8_t *data) {
    (void)area; (void)data;
    lv_display_flush_ready(display);
}

int main(int argc, char **argv) {
    if(argc < 3 || argc > 4) { fprintf(stderr, "Usage: preview state.txt output.ppm [history.csv]\n"); return 1; }
    preview_mode = 1; state_path = argv[1];
    lv_init();
    lv_display_t *display = lv_display_create(WIDTH, HEIGHT);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB888);
    lv_display_set_buffers(display, pixels, NULL, sizeof(pixels), LV_DISPLAY_RENDER_MODE_DIRECT);
    lv_display_set_flush_cb(display, capture_flush);
    create_ui(); refresh(NULL); refresh_inference(NULL);
    const char *next_state = getenv("CABINET_UI_NEXT_STATE");
    if(next_state) { state_path = next_state; refresh(NULL); refresh_inference(NULL); }
#ifdef CABINET_OPERATOR_TEST
    if(!operator_test(getenv("CABINET_OPERATOR_ACTIONS"))) return 1;
#endif
    if(argc == 4 && link_valid) {
        FILE *history = fopen(argv[3], "r");
        if(!history) return 1;
        double rpm, temperature, target;
        unsigned count = 0;
        while(count < 61 && fscanf(history, "%lf,%lf,%lf", &rpm, &temperature, &target) == 3) {
            if(!isfinite(rpm) || !isfinite(temperature) || !isfinite(target)) { fclose(history); return 1; }
            lv_chart_set_next_value(trend_chart, rpm_series, (int32_t)lround(rpm));
            lv_chart_set_next_value(trend_chart, temp_series, (int32_t)lround(temperature * 10));
            lv_chart_set_next_value(trend_chart, target_series, (int32_t)lround(target));
            count++;
        }
        fclose(history);
        if(count) lv_obj_add_flag(trend_empty, LV_OBJ_FLAG_HIDDEN);
        trend_ranges();
    }
    lv_obj_update_layout(lv_screen_active());
    lv_refr_now(display);
    FILE *stream = fopen(argv[2], "wb");
    if(!stream) return 1;
    fprintf(stream, "P6\n%d %d\n255\n", WIDTH, HEIGHT);
    for(size_t offset = 0; offset < sizeof(pixels); offset += 3) {
        uint8_t rgb[3] = {pixels[offset + 2], pixels[offset + 1], pixels[offset]};
        if(fwrite(rgb, 1, 3, stream) != 3) { fclose(stream); return 1; }
    }
    int failed = fclose(stream);
    const char *audit_path = getenv("CABINET_UI_AUDIT");
    if(audit_path) {
        FILE *audit = fopen(audit_path, "w");
        if(!audit) { lv_display_delete(display); return 1; }
        fprintf(audit,"life_hours=%s\nlife_caption=%s\nlife_rpm=%s\nlife_detail=%s\nlife_note=%s\n",lv_label_get_text(life_hours),lv_label_get_text(life_caption),lv_label_get_text(life_rpm),lv_label_get_text(life_detail),lv_label_get_text(life_note));
        int metric_overflow = 0;
        for(int index = 0; index < 4; index++) {
            lv_point_t extent;
            lv_text_get_size(&extent, lv_label_get_text(metrics[index].value), lv_obj_get_style_text_font(metrics[index].value, 0), 0, 0, 10000, LV_TEXT_FLAG_NONE);
            if(extent.x > lv_obj_get_width(metrics[index].value)) metric_overflow++;
            fprintf(audit, "metric_%d_font_height=%d\n", index, lv_obj_get_style_text_font(metrics[index].value, 0)->line_height);
            fprintf(audit, "metric_%d_value=%s\nmetric_%d_width=%d\nmetric_%d_unit_gap=%d\n", index,
                    lv_label_get_text(metrics[index].value), index, extent.x, index,
                    (int)(lv_obj_get_y(metrics[index].unit) - lv_obj_get_y(metrics[index].value) - lv_obj_get_height(metrics[index].value)));
        }
        fprintf(audit, "link_valid=%d\ninterface_mismatch=%d\ncore=%s\ncore_note=%s\ninlet=%s\ncurrent_note=%s\npressure_note=%s\nbanner=%s\nratio=%s\npl_status=%s\nfooter=%s\n",
                link_valid, interface_mismatch, lv_label_get_text(metrics[1].value), lv_label_get_text(metrics[1].note),
                lv_label_get_text(inlet_label), lv_label_get_text(metrics[2].note),
                lv_label_get_text(metrics[3].note), lv_label_get_text(banner_title), lv_label_get_text(ratio_label),
                lv_label_get_text(pl_status_label), lv_label_get_text(footer));
        fprintf(audit, "metric_overflow=%d\ncurrent=%s\ncurrent_unit=%s\n", metric_overflow,
                lv_label_get_text(metrics[2].value), lv_label_get_text(metrics[2].unit));
        fprintf(audit, "current_title=%s\ncurrent_font_height=%d\n", lv_label_get_text(metrics[2].title),
                lv_obj_get_style_text_font(metrics[2].value, 0)->line_height);
        fprintf(audit, "nn_direct_used=%d\nnpu_state=%s\nnpu_note=%s\nnpu_first_group=%s\n", nn_direct_used,
                lv_label_get_text(model_state), lv_label_get_text(model_note), lv_label_get_text(probability_labels[0]));
        lv_color_t speed_color=lv_obj_get_style_bg_color(pl_lights[3][0],0);
        fprintf(audit,"speed_caption=%s\nspeed_color=%02x%02x%02x\n",lv_label_get_text(pl_state_labels[3]),
                speed_color.red,speed_color.green,speed_color.blue);
        for(int i=0;i<3;i++) {
            lv_color_t color=lv_obj_get_style_bg_color(pl_lights[i][0],0);
            fprintf(audit,"monitor_%d_caption=%s\nmonitor_%d_color=%02x%02x%02x\n",i,
                    lv_label_get_text(pl_state_labels[i]),i,color.red,color.green,color.blue);
        }
        unsigned temperature_points=0,rpm_points=0;
        int32_t *temperatures=lv_chart_get_series_y_array(temperature_chart,temp_series);
        int32_t *rpms=lv_chart_get_series_y_array(trend_chart,rpm_series);
        for(uint32_t point=0;point<lv_chart_get_point_count(trend_chart);point++) {
            if(temperatures[point]!=LV_CHART_POINT_NONE) temperature_points++;
            if(rpms[point]!=LV_CHART_POINT_NONE) rpm_points++;
        }
        fprintf(audit,"temperature_trend_points=%u\nrpm_trend_points=%u\n",temperature_points,rpm_points);
        if(operator_window) fprintf(audit, "parameter_revision=%d\nparameter_current_tenths=%d\nparameter_message=%s\nparameter_output_confirmed=0\n", operator_reply.revision, operator_reply.current, lv_label_get_text(operator_message));
        if(fclose(audit)) failed = 1;
    }
    operator_shutdown(); lv_display_delete(display);
    return failed ? 1 : 0;
}
#else
static volatile sig_atomic_t stopping;
static void stop_signal(int number) { (void)number; stopping = 1; }

int main(int argc, char **argv) {
    state_path = argc > 1 ? argv[1] : "/run/cabinet-live/state.txt";
    int lock = open("/run/cabinet-display.lock", O_CREAT | O_RDWR | O_CLOEXEC, 0600);
    if(lock < 0 || flock(lock, LOCK_EX | LOCK_NB) != 0) { perror("display lock"); return 1; }
    int framebuffer = open("/dev/fb0", O_RDWR | O_CLOEXEC);
    struct fb_var_screeninfo variable;
    struct fb_fix_screeninfo fixed;
    if(framebuffer < 0 || ioctl(framebuffer, FBIOGET_VSCREENINFO, &variable) || ioctl(framebuffer, FBIOGET_FSCREENINFO, &fixed)) { perror("framebuffer"); return 1; }
    if(variable.xres != WIDTH || variable.yres != HEIGHT || variable.bits_per_pixel != 24 || fixed.line_length != WIDTH * 3 ||
       variable.xoffset || variable.yoffset || variable.red.offset != 16 || variable.green.offset != 8 || variable.blue.offset != 0 ||
       variable.red.length != 8 || variable.green.length != 8 || variable.blue.length != 8 || fixed.smem_len < WIDTH * HEIGHT * 3) {
        fprintf(stderr, "Unsupported framebuffer layout; unchanged\n"); return 1;
    }
    close(framebuffer);
    int terminal = open("/dev/tty1", O_RDWR | O_NOCTTY | O_CLOEXEC);
    int old_mode;
    if(terminal < 0 || ioctl(terminal, KDGETMODE, &old_mode) || ioctl(terminal, KDSETMODE, KD_GRAPHICS)) { perror("graphical console"); return 1; }
    signal(SIGTERM, stop_signal); signal(SIGINT, stop_signal);
    lv_init();
    lv_display_t *display = lv_linux_fbdev_create();
    if(!display) { ioctl(terminal, KDSETMODE, old_mode); return 1; }
    lv_linux_fbdev_set_file(display, "/dev/fb0");
    if(lv_display_get_horizontal_resolution(display) != WIDTH || lv_display_get_vertical_resolution(display) != HEIGHT) { ioctl(terminal, KDSETMODE, old_mode); return 1; }
    create_ui(); refresh(NULL);
    const char *input_paths[] = {getenv("CABINET_OPERATOR_POINTER"), getenv("CABINET_OPERATOR_KEYBOARD")};
    lv_indev_t *inputs[2] = {NULL, NULL};
    int input_failure = 0;
    if(operator_socket) for(int index = 0; index < 2; index++) {
        if(!input_paths[index]) continue;
        struct stat info;
        if(strncmp(input_paths[index], "/dev/input/event", 16) || lstat(input_paths[index], &info) || !S_ISCHR(info.st_mode)) {
            fprintf(stderr, "Invalid explicitly selected operator input\n"); input_failure = stopping = 1; break;
        }
        inputs[index] = lv_evdev_create(index ? LV_INDEV_TYPE_KEYPAD : LV_INDEV_TYPE_POINTER, input_paths[index]);
        if(!inputs[index]) { fprintf(stderr, "Operator input unavailable\n"); input_failure = stopping = 1; break; }
        if(index) lv_indev_set_group(inputs[index], operator_group);
        else {
            lv_obj_t *cursor = lv_obj_create(lv_screen_active()); lv_obj_set_size(cursor, 8, 8); set_bg_color(cursor, lv_color_hex(TEXT), 0);
            lv_obj_remove_flag(cursor, LV_OBJ_FLAG_CLICKABLE); lv_indev_set_cursor(inputs[index], cursor);
        }
    }
    lv_timer_create(refresh, 200, NULL);
    lv_timer_create(refresh_inference, 50, NULL);
    while(!stopping) {
        uint32_t delay = lv_timer_handler();
        if(delay > 20) delay = 20;
        struct timespec sleep_time = {0, (long)(delay ? delay : 1) * 1000000};
        nanosleep(&sleep_time, NULL);
    }
    operator_shutdown();
    for(int index = 0; index < 2; index++) if(inputs[index]) lv_evdev_delete(inputs[index]);
    lv_display_delete(display);
    ioctl(terminal, KDSETMODE, old_mode);
    close(terminal); close(lock);
    return input_failure ? 1 : 0;
}
#endif
