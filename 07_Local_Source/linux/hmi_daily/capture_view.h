#ifndef CABINET_CAPTURE_VIEW_H
#define CABINET_CAPTURE_VIEW_H

static lv_obj_t *capture_status_label, *capture_identity_label, *capture_installation_label;
static lv_obj_t *capture_duration_label, *capture_label_label, *capture_path_label;
static lv_obj_t *capture_progress, *capture_counts[4], *capture_gate_label;
static lv_obj_t *capture_reason_label, *capture_provenance_label, *capture_note_label;

static void create_capture_ui(lv_obj_t *screen) {
    lv_obj_add_flag(lv_obj_get_parent(trend_chart), LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(lv_obj_get_parent(model_state), LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(lv_obj_get_parent(baseline_score), LV_OBJ_FLAG_HIDDEN);
    lv_obj_t *card = panel(screen, 12, 388, 360, 304, PANEL);
    label(card, 12, 10, 336, &ui_zh_20, TEXT, "实验会话 / SESSION");
    capture_status_label = label(card, 12, 46, 336, &ui_zh_28, MUTED, "等待开始记录");
    capture_identity_label = label(card, 12, 88, 336, &lv_font_montserrat_12, TEXT, "ID --");
    capture_installation_label = label(card, 12, 114, 336, &ui_zh_16, MUTED, "安装 -- | 记录人 --");
    capture_label_label = label(card, 12, 140, 336, &ui_zh_18, AMBER, "工况 未标注 / 待人工审核");
    capture_duration_label = label(card, 12, 172, 336, &lv_font_montserrat_28, TEAL, "-- / -- s");
    capture_progress = bar(card, 12, 212, 336, 8, TEAL);
    capture_path_label = label(card, 12, 236, 336, &lv_font_montserrat_12, TEXT, "--");
    lv_label_set_long_mode(capture_path_label, LV_LABEL_LONG_DOT);
    inlet_label = label(card, 12, 262, 336, &ui_zh_16, TEAL, "进风 --℃ · RH --% | AHT20");
    ambient_label = label(card, 12, 282, 336, &ui_zh_16, MUTED, "环境气压 -- hPa | BMP280");

    card = panel(screen, 896, 276, 372, 208, PANEL);
    label(card, 12, 10, 348, &ui_zh_18, TEXT, "记录完整性 / 数据落盘");
    const char *names[4] = {"合格帧", "拒收帧", "已落盘", "丢帧事件"};
    for(int index = 0; index < 4; index++) {
        int left = 12 + index % 2 * 176, top = 42 + index / 2 * 70;
        label(card, left, top, 164, &ui_zh_16, MUTED, names[index]);
        capture_counts[index] = label(card, left, top + 22, 164, &lv_font_montserrat_28, TEXT, "--");
    }
    capture_gate_label = label(card, 12, 182, 348, &ui_zh_16, AMBER, "归档不代表训练资格");

    card = panel(screen, 896, 494, 372, 198, PANEL);
    label(card, 12, 10, 348, &ui_zh_18, TEXT, "采集门禁 / 版本证据");
    capture_reason_label = label(card, 12, 42, 348, &ui_zh_16, MUTED, "等待真实数据");
    lv_label_set_long_mode(capture_reason_label, LV_LABEL_LONG_WRAP);
    lv_obj_set_height(capture_reason_label, 48);
    capture_provenance_label = label(card, 12, 94, 348, &lv_font_montserrat_12, TEXT, "CFG -- | CAL -- | Q --");
    capture_note_label = label(card, 12, 120, 348, &ui_zh_16, AMBER, "标签待审核 · 模型未训练");
    label(card, 12, 146, 348, &ui_zh_16, MUTED, "网页学习独立保留，不改保护");
    label(card, 12, 171, 348, &ui_zh_16, MUTED, "只读显示 · 电脑命令开始 / 停止");
}

static void refresh_capture(void) {
    int available = strcmp(value("capture_schema"), "capture-v1") == 0;
    const char *state = available ? value("capture_state") : "UNAVAILABLE";
    uint32_t color = MUTED;
    const char *title = "等待开始记录";
    if(strcmp(state, "RECORDING") == 0) { title = "正在记录 / REC"; color = TEAL; }
    else if(strcmp(state, "COMPLETED") == 0) { title = "已保存 / 待审核"; color = AMBER; }
    else if(strcmp(state, "DIAGNOSTIC_SAVED") == 0) { title = "调试归档 / 不训练"; color = AMBER; }
    else if(strcmp(state, "ABORTED") == 0 || strcmp(state, "ERROR") == 0) { title = "记录中止 / 检查原因"; color = RED; }
    else if(!available) { title = "记录服务未启用"; }
    if(!link_valid && strcmp(state, "RECORDING") == 0) { title = "采集失鲜 / 记录未确认"; color = RED; }
    set_text(capture_status_label, title);
    lv_obj_set_style_text_color(capture_status_label, lv_color_hex(color), 0);
    char text[512];
    snprintf(text, sizeof(text), "ID %s", available ? value("capture_session_id") : "--");
    set_text(capture_identity_label, text);
    snprintf(text, sizeof(text), "安装 %s | 记录人 %s", value("capture_installation_id"), value("capture_operator"));
    set_text(capture_installation_label, text);
    const char *label_name = value("capture_label");
    const char *chinese = strcmp(label_name, "normal") == 0 ? "正常" : strcmp(label_name, "imbalance") == 0 ? "失衡" :
        strcmp(label_name, "stall") == 0 ? "卡死" : strcmp(label_name, "clog") == 0 ? "堵塞" :
        strcmp(label_name, "overheat") == 0 ? "过热" : "未标注";
    snprintf(text, sizeof(text), "工况 %s / 待人工审核", chinese);
    set_text(capture_label_label, text);
    snprintf(text, sizeof(text), "%s / %s s", value("capture_elapsed_s"), value("capture_duration_s"));
    set_text(capture_duration_label, text);
    double elapsed = 0, duration = 0;
    int progress = available && numeric("capture_elapsed_s", &elapsed) && numeric("capture_duration_s", &duration) && duration > 0;
    bar_value(capture_progress, progress ? elapsed / duration : 0, progress, color);
    const char *path = value("capture_file");
    const char *session = value("capture_session_id");
    snprintf(text, sizeof(text), "%s/frames.jsonl", session);
    set_text(capture_path_label, available && strcmp(path, "--") != 0 ? text : "--");
    const char *counts[4] = {"capture_accepted", "capture_rejected", "capture_durable_frames", "capture_gaps"};
    for(int index = 0; index < 4; index++) set_text(capture_counts[index], available ? value(counts[index]) : "--");
    set_text(capture_gate_label, "合格帧仅指数据合同，不是健康结论");
    const char *reason = available ? value("capture_ready_reason") : "CAPTURE_NOT_ENABLED";
    if(!link_valid) reason = "COLLECTOR_STALE / 不使用旧值";
    else if(strcmp(value("capture_ready"), "1") == 0) reason = "真实帧合同通过 · 标签仍待审核";
    snprintf(text, sizeof(text), "%s", reason);
    set_text(capture_reason_label, text);
    snprintf(text, sizeof(text), "CFG %s | CAL %s | Q %s", value("frame_contract_current"), value("frame_calibrated"), value("quality"));
    set_text(capture_provenance_label, text);
    snprintf(text, sizeof(text), "%s", available ? value("capture_reason") : "没有录制服务，不代表没有传感器数据");
    set_text(capture_note_label, text);
    snprintf(text, sizeof(text), "风冷测控 · 实验记录 | %s", link_valid ? value("panel_source") : "WAIT");
    set_text(title_label, text);
    snprintf(text, sizeof(text), "[ %s | PL L%s | %s ]", state, link_valid ? value("panel_level") : "--",
             strcmp(value("capture_capture_mode"), "DIAGNOSTIC") == 0 ? "调试数据不训练" : "标签待审核");
    set_text(banner_title, text);
    lv_obj_set_style_text_color(banner_title, lv_color_hex(color), 0);
    lv_obj_set_style_border_color(banner, lv_color_hex(color), 0);
    snprintf(text, sizeof(text), "A/B 径向传递比 ratio_ab = %s", link_valid ? value("daily_ratio_ab") : "--");
    set_text(ratio_label, text);
    for(int band = 0; band < 8; band++) {
        char key[48];
        snprintf(key, sizeof(key), "panel_band%d_hz", band);
        set_text(band_labels[band], link_valid ? value(key) : "--");
    }
    snprintf(text, sizeof(text), "%s完整原字保存至JSONL，CSV由审核导出 · 不在线训练NPU · 不修改健康基线或硬保护",
             preview_mode ? "合成预览 / 未连接开发板 · " : "");
    set_text(footer, text);
    if(interface_mismatch) {
        set_text(banner_title, "[ 显示接口版本不匹配 ]");
        set_text(footer, "请同步采集服务与显示程序 · 不使用旧接口数据");
    }
}

#endif
