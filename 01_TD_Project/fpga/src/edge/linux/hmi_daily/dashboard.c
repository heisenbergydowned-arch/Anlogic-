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
static lv_obj_t *trend_chart, *trend_empty, *trend_max;
static lv_obj_t *inlet_label;
static lv_chart_series_t *rpm_series, *temp_series, *target_series;
static lv_obj_t *band_chart, *band_empty, *band_labels[8];
static lv_chart_series_t *band_series[2];
static lv_obj_t *icm_raw_panel, *icm_raw_lines[2], *icm_raw_info[2];
static lv_obj_t *pl_boxes[6], *pl_lights[5][9], *pl_sensor_dot, *pl_sensor_label, *pl_status_label;
static lv_obj_t *model_state, *model_note, *probability_labels[5], *probability_bars[5];
static lv_obj_t *baseline_score, *baseline_bar, *baseline_badge, *baseline_badge_label, *baseline_scope;
static lv_obj_t *group_bars[4], *group_values[4];
static uint64_t last_plot, sequence_progress;
static char previous_sequence[64], previous_plot_sequence[64], previous_contract[256];
static int link_valid, preview_mode, interface_mismatch;
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

static int environment_current(const char *key) {
    const char *text = value(key);
    char *end;
    if(!link_valid || *text < '0' || *text > '9') return 0;
    unsigned long long deadline = strtoull(text, &end, 10);
    uint64_t now = milliseconds();
    return end != text && !*end && deadline >= now && deadline - now <= 2500;
}

static void set_text(lv_obj_t *object, const char *text) {
    if(strcmp(lv_label_get_text(object), text) != 0) lv_label_set_text(object, text);
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
    lv_obj_set_style_bg_color(object, lv_color_hex(valid ? color : 0x222c37), LV_PART_INDICATOR);
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
        metrics[index].title = label(card, 12, 10, 150, index == 2 ? &ui_zh_16 : &ui_zh_18, TEXT, names[index]);
        metrics[index].value = label_aligned(card, 10, index == 2 ? 48 : 38, 100,
                                            index == 2 ? &lv_font_montserrat_28 : &lv_font_montserrat_44,
                                            MUTED, LV_TEXT_ALIGN_RIGHT, "--");
        metrics[index].unit = label(card, 116, 56, 50, &ui_zh_16, MUTED, "--");
        metrics[index].note = label_aligned(card, 8, 98, 158, &ui_zh_16, MUTED, LV_TEXT_ALIGN_CENTER, "等待有效采样");
        metrics[index].bar = index == 0 || index == 3 ? bar(card, 12, 130, 150, 5, TEAL) : NULL;
    }
}

static void create_trend(lv_obj_t *screen) {
    lv_obj_t *card = panel(screen, 12, 388, 360, 304, PANEL);
    label(card, 12, 10, 210, &ui_zh_18, TEXT, "转速 / 核心温度 (60s)");
    label(card, 212, 12, 72, &ui_zh_16, TEAL, "- RPM");
    label(card, 282, 12, 72, &ui_zh_16, AMBER, "- 核心℃");
    trend_chart = lv_chart_create(card);
    lv_obj_set_pos(trend_chart, 42, 46);
    lv_obj_set_size(trend_chart, 304, 164);
    chart_style(trend_chart);
    lv_chart_set_type(trend_chart, LV_CHART_TYPE_LINE);
    lv_chart_set_point_count(trend_chart, 61);
    lv_chart_set_axis_range(trend_chart, LV_CHART_AXIS_PRIMARY_Y, 0, rpm_axis_max);
    lv_chart_set_axis_range(trend_chart, LV_CHART_AXIS_SECONDARY_Y, -55, 125);
    lv_chart_set_div_line_count(trend_chart, 6, 7);
    rpm_series = lv_chart_add_series(trend_chart, lv_color_hex(TEAL), LV_CHART_AXIS_PRIMARY_Y);
    temp_series = lv_chart_add_series(trend_chart, lv_color_hex(AMBER), LV_CHART_AXIS_SECONDARY_Y);
    target_series = lv_chart_add_series(trend_chart, lv_color_hex(MUTED), LV_CHART_AXIS_PRIMARY_Y);
    lv_chart_set_all_values(trend_chart, rpm_series, LV_CHART_POINT_NONE);
    lv_chart_set_all_values(trend_chart, temp_series, LV_CHART_POINT_NONE);
    lv_chart_set_all_values(trend_chart, target_series, LV_CHART_POINT_NONE);
    trend_max = label(card, 4, 44, 38, &lv_font_montserrat_12, MUTED, "6000");
    label(card, 6, 82, 36, &lv_font_montserrat_12, MUTED, "4500");
    label(card, 6, 120, 36, &lv_font_montserrat_12, MUTED, "3000");
    label(card, 6, 158, 36, &lv_font_montserrat_12, MUTED, "1500");
    label(card, 20, 194, 20, &lv_font_montserrat_12, MUTED, "0");
    for(int tick = 0; tick < 7; tick++) {
        char text[12];
        snprintf(text, sizeof(text), tick == 6 ? "60s" : "%d", tick * 10);
        label(card, 38 + tick * 49, 214, 36, &lv_font_montserrat_12, MUTED, text);
    }
    trend_empty = label_aligned(card, 64, 108, 250, &ui_zh_18, MUTED, LV_TEXT_ALIGN_CENTER, "暂无有效趋势");
    label(card, 12, 236, 336, &ui_zh_16, MUTED, "温度轴 -55~125℃ · 灰线=目标");
    inlet_label = label(card, 12, 262, 336, &ui_zh_16, TEAL, "进风 --℃ · RH --% | AHT20");
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
    ratio_box = panel_styled(card, 154, 258, 336, 36, 0x102329, 0x2b7a80, 4);
    ratio_label = label_aligned(ratio_box, 8, 8, 320, &ui_zh_16, TEAL, LV_TEXT_ALIGN_CENTER, "A/B 径向传递比 ratio_ab = --");
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
    lv_chart_set_axis_range(band_chart, LV_CHART_AXIS_PRIMARY_Y, 0, 400);
    lv_chart_set_div_line_count(band_chart, 5, 0);
    for(int point = 0; point < 2; point++) {
        band_series[point] = lv_chart_add_series(band_chart, lv_color_hex(point ? BLUE : TEAL), LV_CHART_AXIS_PRIMARY_Y);
        lv_chart_set_all_values(band_chart, band_series[point], LV_CHART_POINT_NONE);
    }
    label(card, 6, 44, 34, &lv_font_montserrat_12, MUTED, "0.40");
    label(card, 6, 90, 34, &lv_font_montserrat_12, MUTED, "0.30");
    label(card, 6, 136, 34, &lv_font_montserrat_12, MUTED, "0.20");
    label(card, 6, 182, 34, &lv_font_montserrat_12, MUTED, "0.10");
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
    label(card, 12, 10, 348, &ui_zh_18, TEXT, "第1层 · PL 硬件确定性保护 (100MHz)");
    const char *zh_names[5] = {"过流", "过热", "堵转", "超速", "振动"};
    const char *en_names[5] = {"OC", "OT", "STALL", "OS", "VIB"};
    for(int index = 0; index < 5; index++) {
        int left = 12 + (index % 3) * 118, top = 38 + (index / 3) * 58;
        pl_boxes[index] = panel_styled(card, left, top, 112, 52, SUBPANEL, EDGE, 4);
        for(int dot = 0; dot < 9; dot++) {
            int dx = 10 + (dot % 3) * 9, dy = 11 + (dot / 3) * 9;
            pl_lights[index][dot] = panel_styled(pl_boxes[index], dx, dy, 6, 6, EDGE, 0, 2);
        }
        label(pl_boxes[index], 44, 6, 64, &ui_zh_16, TEXT, zh_names[index]);
        label(pl_boxes[index], 44, 27, 64, &lv_font_montserrat_16, MUTED, en_names[index]);
    }
    pl_boxes[5] = panel_styled(card, 12 + 2 * 118, 38 + 58, 112, 52, SUBPANEL, EDGE, 4);
    pl_sensor_dot = panel_styled(pl_boxes[5], 49, 9, 14, 10, EDGE, 0, 4);
    pl_sensor_label = label_aligned(pl_boxes[5], 4, 25, 104, &ui_zh_16, TEXT, LV_TEXT_ALIGN_CENTER, "传感器正常");
    pl_status_label = label(card, 12, 164, 348, &ui_zh_16, MUTED, "PWM -- | PI --");

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
    label(card, 12, 10, 348, &ui_zh_18, TEXT, "第3层 · 工况健康基线");
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
    footer = label(screen, 12, 698, 1256, &ui_zh_16, MUTED, "显示不控制风机 · FPGA保护独立 · 网页发起学习");
#ifdef CABINET_RECORDING
    create_capture_ui(screen);
#endif
    create_operator_ui(screen, top_bar);
}

static void clear_trend(void) {
    lv_chart_set_all_values(trend_chart, rpm_series, LV_CHART_POINT_NONE);
    lv_chart_set_all_values(trend_chart, temp_series, LV_CHART_POINT_NONE);
    lv_chart_set_all_values(trend_chart, target_series, LV_CHART_POINT_NONE);
    lv_obj_remove_flag(trend_empty, LV_OBJ_FLAG_HIDDEN);
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
        if(valid) snprintf(text, sizeof(text), index == 0 ? "%.0f" : index == 2 ? "%.2f" : index == 3 ? "%+.3g" : "%.1f", measured);
        else snprintf(text, sizeof(text), "--");
        set_text(metrics[index].value, text);
        uint32_t color = valid ? (index == 1 ? AMBER : TEAL) : MUTED;
        lv_obj_set_style_text_color(metrics[index].value, lv_color_hex(color), 0);
        lv_obj_set_style_text_color(metrics[index].unit, lv_color_hex(color), 0);

        const char *unit = index == 1 ? "℃" : value(units[index]);
        if(index == 0 && valid) unit = "RPM";
        if(index == 3 && valid && strcmp(unit, "kPa") == 0) {
            snprintf(text, sizeof(text), "%+.0f", measured * 1000);
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
            lv_obj_set_style_text_font(metrics[index].value, &lv_font_montserrat_28, 0);
            lv_point_t extent;
            lv_text_get_size(&extent, lv_label_get_text(metrics[index].value), &lv_font_montserrat_28, 0, 0, 10000, LV_TEXT_FLAG_NONE);
            if(extent.x > 100) {
                overflow = 1;
                valid = 0;
                set_text(metrics[index].value, "--");
                lv_obj_set_style_text_color(metrics[index].value, lv_color_hex(MUTED), 0);
                lv_obj_set_style_text_color(metrics[index].unit, lv_color_hex(MUTED), 0);
            }
        } else {
            const lv_font_t *fonts[] = {&lv_font_montserrat_44, &lv_font_montserrat_28, &lv_font_montserrat_20, &lv_font_montserrat_16};
            for(size_t font_index = 0; font_index < sizeof(fonts) / sizeof(fonts[0]); font_index++) {
                lv_point_t extent;
                lv_text_get_size(&extent, lv_label_get_text(metrics[index].value), fonts[font_index], 0, 0, 10000, LV_TEXT_FLAG_NONE);
                if(extent.x <= 100 || font_index == sizeof(fonts) / sizeof(fonts[0]) - 1) {
                    lv_obj_set_style_text_font(metrics[index].value, fonts[font_index], 0);
                    break;
                }
            }
        }
        set_text(metrics[index].unit, valid ? unit : "--");

        int target_valid = valid && index == 0 && numeric("daily_target", &target) && target > 0;
        if(overflow) {
            snprintf(text, sizeof(text), "数值超出显示范围");
        } else if(!valid) {
            snprintf(text, sizeof(text), "不显示旧值或推测值");
        } else if(strcmp(unit, "原始码") == 0) {
            snprintf(text, sizeof(text), index == 2 ? "未标定 · 非电流值" : "未标定 / 不能换算单位");
        } else if(target_valid) {
            snprintf(text, sizeof(text), "目标 %.0f | PWM %s", target, value("panel_pwm"));
        } else if(index == 1) {
            snprintf(text, sizeof(text), "DS18B20 · 核心器件");
        } else if(index == 2) {
            snprintf(text, sizeof(text), "AD7606 · 电流");
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
    set_text(matrix_title,raw_valid ? "振动诊断 / 原始码 / 未标定" : "双测点时域特征矩阵 (18维)");
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
    snprintf(text, sizeof(text),raw_valid ? "RAW A/B ratio = %s" : "A/B 径向传递比 ratio_ab = %s", raw_valid ? value("raw_feature_ratio_ab") : valid ? value("daily_ratio_ab") : "--");
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

static void update_decisions(void) {
    const char *channels[6] = {"oc", "ot", "stall", "os", "vib", "sensor"};
    int any_fault = 0, any_unknown = 0;
    for(int index = 0; index < 6; index++) {
        char key[64];
        snprintf(key, sizeof(key), "panel_pl_%s", channels[index]);
        const char *state = link_valid ? value(key) : "UNKNOWN";
        uint32_t color = strcmp(state, "CLEAR") == 0 ? GREEN :
                         strcmp(state, "WARN") == 0 ? AMBER :
                         (strcmp(state, "ALARM") == 0 || strcmp(state, "LATCH") == 0) ? RED : 0x2c3742;
        uint32_t border = color == GREEN ? 0x1e4d3b : color == AMBER ? 0x6b5125 : color == RED ? 0x7a272c : EDGE;
        if(color == RED || color == AMBER) any_fault = 1;
        if(color == 0x2c3742) any_unknown = 1;
        lv_obj_set_style_border_color(pl_boxes[index], lv_color_hex(border), 0);
        if(index < 5) {
            for(int dot = 0; dot < 9; dot++)
                lv_obj_set_style_bg_color(pl_lights[index][dot], lv_color_hex(color), 0);
        } else {
            lv_obj_set_style_bg_color(pl_sensor_dot, lv_color_hex(color), 0);
            const char *sensor_text = color == GREEN ? "传感器正常" : color == AMBER ? "传感器预警" :
                                      color == RED ? "传感器异常" : "传感器未确认";
            set_text(pl_sensor_label, sensor_text);
            lv_obj_set_style_text_color(pl_sensor_label, lv_color_hex(color == 0x2c3742 ? MUTED : TEXT), 0);
        }
    }
    char text[256];
    if(link_valid) {
        snprintf(text, sizeof(text), "PWM %s | %s", value("panel_drive_status"), value("panel_pi"));
        lv_obj_set_style_text_color(pl_status_label, lv_color_hex(any_fault ? AMBER : any_unknown ? MUTED : GREEN), 0);
    } else {
        snprintf(text, sizeof(text), "Status: 驱动状态未知 | PI 未确认");
        lv_obj_set_style_text_color(pl_status_label, lv_color_hex(MUTED), 0);
    }
    set_text(pl_status_label, text);

    int model_valid = link_valid && strcmp(value("panel_model_valid"), "1") == 0;
    snprintf(text, sizeof(text), "第2层 · 本地五分类推理 (%s)", model_valid ? value("panel_model_state") : "未就绪");
    set_text(model_state, text);
    set_text(model_note, model_valid ? value("panel_model_note") : "没有新鲜的真实模型结果");
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
        lv_obj_set_style_text_color(probability_labels[index], lv_color_hex(valid ? (index == 0 ? GREEN : TEXT) : MUTED), 0);
        bar_value(probability_bars[index], valid ? probability / 100.0 : 0, valid, index == 0 ? GREEN : TEAL);
    }

    double score = 0, limit = 0;
    int baseline_valid = link_valid && strcmp(value("panel_baseline_valid"), "1") == 0 && numeric("ui_learn_score", &score) &&
                         numeric("panel_baseline_limit", &limit) && limit > 0;
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

static void update_trend(void) {
    uint64_t now = milliseconds();
    double rpm = 0, temperature = 0, target = 0;
    int rpm_valid = link_valid && strcmp(value("daily_rpm_valid"), "1") == 0 && numeric("daily_rpm_value", &rpm) && rpm >= 0;
    int temperature_valid = link_valid && strcmp(value("core_temperature_valid"), "1") == 0 &&
                            strcmp(value("core_temperature_source"), "DS18B20/S4b") == 0 &&
                            numeric("core_temperature_c", &temperature) && temperature >= -55 && temperature <= 125;
    char contract[256];
    snprintf(contract, sizeof(contract), "%s/%s/%s", value("panel_source"), value("panel_sample_mode"), value("ui_configuration"));
    if(strcmp(contract, previous_contract) != 0 || !link_valid || now - last_plot > 2500) {
        clear_trend();
        snprintf(previous_contract, sizeof(previous_contract), "%s", contract);
    }
    if(!rpm_valid) lv_chart_set_all_values(trend_chart, rpm_series, LV_CHART_POINT_NONE);
    if(!temperature_valid) lv_chart_set_all_values(trend_chart, temp_series, LV_CHART_POINT_NONE);
    if((!rpm_valid && !temperature_valid) || now - last_plot < 1000) return;
    int new_observation = strcmp(previous_plot_sequence, value("sequence")) != 0;
    if(!new_observation) return;
    lv_chart_set_next_value(trend_chart, rpm_series, rpm_valid ? (int32_t)lround(rpm) : LV_CHART_POINT_NONE);
    lv_chart_set_next_value(trend_chart, temp_series, temperature_valid ? (int32_t)lround(temperature) : LV_CHART_POINT_NONE);
    int target_valid = rpm_valid && numeric("daily_target", &target) && target >= 0;
    lv_chart_set_next_value(trend_chart, target_series, target_valid ? (int32_t)lround(target) : LV_CHART_POINT_NONE);
    if(rpm_valid) {
        if(rpm > rpm_axis_max || (target_valid && target > rpm_axis_max)) {
            rpm_axis_max = (int)(fmax(rpm, target_valid ? target : rpm) / 1000 + 1) * 1000;
            lv_chart_set_axis_range(trend_chart, LV_CHART_AXIS_PRIMARY_Y, 0, rpm_axis_max);
            char text[24];
            snprintf(text, sizeof(text), "%d", rpm_axis_max);
            set_text(trend_max, text);
        }
    }
    lv_obj_add_flag(trend_empty, LV_OBJ_FLAG_HIDDEN);
    snprintf(previous_plot_sequence, sizeof(previous_plot_sequence), "%s", value("sequence"));
    last_plot = now;
}

static void refresh(lv_timer_t *timer) {
    (void)timer;
    read_fields();
    char text[512];
    uint32_t color = !link_valid ? RED : strcmp(value("ui_severity"), "0") == 0 ? GREEN : strcmp(value("ui_severity"), "3") == 0 ? RED : AMBER;
    uint32_t bg = color == GREEN ? 0x0f2922 : color == AMBER ? 0x2c2212 : 0x2d1418;
    if(link_valid && strcmp(value("ui_severity"), "0") == 0) {
        snprintf(text, sizeof(text), "[ %s | L%s · 无硬件告警 ]", value("panel_mode"), value("panel_level"));
    } else if(link_valid) {
        snprintf(text, sizeof(text), "[ %s · %s | 告警等级 L%s ]", value("panel_mode"), value("ui_banner_title"), value("panel_level"));
    } else {
        snprintf(text, sizeof(text), "%s", interface_mismatch ? "[ 显示接口版本不匹配 ]" : "[ OFFLINE · 硬件数据读取失效 ]");
    }
    set_text(banner_title, text);
    lv_obj_set_style_text_color(banner_title, lv_color_hex(color), 0);
    lv_obj_set_style_border_color(banner, lv_color_hex(color), 0);
    lv_obj_set_style_bg_color(banner, lv_color_hex(bg), 0);

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
    int aht_current = environment_current("environment_aht_deadline_ms") && strcmp(value("inlet_source"), "AHT20") == 0;
    snprintf(text, sizeof(text), "进风 %s℃ · RH %s%% | AHT20", aht_current ? value("inlet_temperature_c") : "--",
             aht_current ? value("relative_humidity_pct") : "--");
    set_text(inlet_label, text);
    snprintf(text, sizeof(text), "%s%s", preview_mode ? "UI预览 / 合成数据 / 不连接硬件 · " : "", link_valid ? value("daily_notice") : interface_mismatch ? "请同步采集服务与显示程序 · 不使用旧接口数据" : "采集失效 · 不使用旧值 · FPGA保护不依赖显示");
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
    create_ui(); refresh(NULL);
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
            lv_chart_set_next_value(trend_chart, temp_series, (int32_t)lround(temperature));
            lv_chart_set_next_value(trend_chart, target_series, (int32_t)lround(target));
            count++;
        }
        fclose(history);
        if(count) lv_obj_add_flag(trend_empty, LV_OBJ_FLAG_HIDDEN);
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
        int metric_overflow = 0;
        for(int index = 0; index < 4; index++) {
            lv_point_t extent;
            lv_text_get_size(&extent, lv_label_get_text(metrics[index].value), lv_obj_get_style_text_font(metrics[index].value, 0), 0, 0, 10000, LV_TEXT_FLAG_NONE);
            if(extent.x > lv_obj_get_width(metrics[index].value)) metric_overflow++;
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
        unsigned temperature_points=0,rpm_points=0;
        int32_t *temperatures=lv_chart_get_series_y_array(trend_chart,temp_series);
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
            lv_obj_t *cursor = lv_obj_create(lv_screen_active()); lv_obj_set_size(cursor, 8, 8); lv_obj_set_style_bg_color(cursor, lv_color_hex(TEXT), 0);
            lv_obj_remove_flag(cursor, LV_OBJ_FLAG_CLICKABLE); lv_indev_set_cursor(inputs[index], cursor);
        }
    }
    lv_timer_create(refresh, 200, NULL);
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
