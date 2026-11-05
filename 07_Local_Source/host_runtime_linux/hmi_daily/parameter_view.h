#ifndef CABINET_PARAMETER_VIEW_H
#define CABINET_PARAMETER_VIEW_H
#include <pthread.h>
#include "parameter_wire.h"

static lv_obj_t *operator_window, *operator_title, *operator_values, *operator_message, *operator_open;
static lv_obj_t *operator_buttons[6];
static lv_group_t *operator_group;
static const char *operator_socket;
static parameter_reply_t operator_reply, operator_worker_reply;
static int operator_valid, operator_candidate, operator_preview, operator_busy, operator_ready, operator_success, operator_created;
static unsigned operator_calls;
static unsigned long long operator_deadline;
static pthread_mutex_t operator_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_t operator_thread;
static char operator_request[1024], operator_call_id[33];

static void *operator_worker(void *unused) {
    (void)unused;
    int result = parameter_exchange(operator_socket, operator_request, operator_call_id, &operator_worker_reply);
    pthread_mutex_lock(&operator_mutex); operator_success = result; operator_ready = 1; pthread_mutex_unlock(&operator_mutex);
    return NULL;
}

static void operator_action(int action) {
    if(action == 5) { lv_obj_add_flag(operator_window, LV_OBJ_FLAG_HIDDEN); operator_preview = 0; lv_group_focus_obj(operator_open); return; }
    if(operator_busy || !operator_socket) return;
    if(action == 1 || action == 2) {
        if(operator_valid && operator_reply.enabled) {
            int candidate = operator_candidate + (action == 1 ? -1 : 1);
            if(candidate >= operator_reply.minimum && candidate <= operator_reply.maximum) operator_candidate = candidate;
            operator_preview = 0;
        }
        return;
    }
    snprintf(operator_call_id, sizeof(operator_call_id), "%016llx%08x%08x", parameter_now(), (unsigned)getpid(), ++operator_calls);
    const char *operation = action == 3 ? "preview" : action == 4 ? "commit" : "status";
    char payload[512] = "{}";
    if(action == 3) {
        if(!operator_valid || !operator_reply.enabled || !parameter_hex(operator_reply.context, 64)) return;
        snprintf(payload, sizeof(payload), "{\"request_id\":\"%s\",\"revision\":%d,\"context_token\":\"%s\",\"setpoint_tenths\":%d}",
                 operator_call_id, operator_reply.revision, operator_reply.context, operator_candidate);
    }
    if(action == 4) {
        if(!operator_preview || parameter_now() > operator_deadline || !parameter_hex(operator_reply.nonce, 32) || !parameter_hex(operator_reply.request_id, 32)) return;
        snprintf(payload, sizeof(payload), "{\"request_id\":\"%s\",\"nonce\":\"%s\"}", operator_reply.request_id, operator_reply.nonce);
        operator_preview = 0;
    }
    snprintf(operator_request, sizeof(operator_request), "{\"schema\":\"cabinet-parameter-local-v1\",\"call_id\":\"%s\",\"operation\":\"%s\",\"payload\":%s}\n", operator_call_id, operation, payload);
    operator_busy = 1; operator_ready = 0;
    set_text(operator_message, "Waiting for collector. This is NOT output confirmation.");
    if(pthread_create(&operator_thread, NULL, operator_worker, NULL) != 0) {
        operator_busy = 0; operator_valid = operator_preview = 0;
        set_text(operator_message, "Worker unavailable. NOT confirmed; refresh before retry.");
    } else operator_created = 1;
}

static void operator_clicked(lv_event_t *event) { operator_action((int)(uintptr_t)lv_event_get_user_data(event)); }

static void operator_show(lv_event_t *event) {
    (void)event; lv_obj_remove_flag(operator_window, LV_OBJ_FLAG_HIDDEN);
    lv_group_focus_obj(operator_buttons[0]); operator_action(0);
}

static void operator_refresh(void) {
    if(!operator_window) return;
    set_text(footer, "Local PS parameter changes require a commissioned owner. PL protections remain independent. No power switching.");
    pthread_mutex_lock(&operator_mutex);
    int ready = operator_ready, success = operator_success;
    if(ready) { operator_ready = 0; if(success) operator_reply = operator_worker_reply; }
    pthread_mutex_unlock(&operator_mutex);
    if(ready) {
        if(operator_created) { pthread_join(operator_thread, NULL); operator_created = 0; }
        operator_busy = 0; operator_valid = success;
        if(!success) {
            operator_preview = 0;
            set_text(operator_message, "Unavailable or reply mismatch. NOT confirmed. Refresh; do not assume retry is safe.");
        } else if(strcmp(operator_reply.state, "PREVIEW_NOT_APPLIED") == 0) {
            operator_preview = 1; operator_deadline = parameter_now() + 29000;
            set_text(operator_message, "PREVIEW ONLY - not applied. Confirm within 29 seconds.");
        } else {
            operator_preview = 0;
            operator_candidate = operator_reply.current;
            if(operator_candidate < operator_reply.minimum) operator_candidate = operator_reply.minimum;
            if(operator_candidate > operator_reply.maximum) operator_candidate = operator_reply.maximum;
            if(strcmp(operator_reply.last_state, "APPLIED_PS_SETPOINT_NOT_PL_OUTPUT_CONFIRMATION") == 0)
                set_text(operator_message, "PS setpoint applied. Actual RPM/PWM output is NOT confirmed.");
            else if(strcmp(operator_reply.state, "QUEUED_NOT_APPLIED") == 0) set_text(operator_message, "QUEUED only - press Refresh for the collector receipt.");
            else if(!operator_reply.enabled) set_text(operator_message, "Writes disabled. Commissioned live owner and local profile are required.");
            else set_text(operator_message, "Read complete. Adjust candidate, then Preview and Confirm.");
        }
    }
    if(operator_preview && parameter_now() > operator_deadline) { operator_preview = 0; set_text(operator_message, "Preview expired. Refresh and preview again; nothing was submitted."); }
    char text[256];
    if(operator_valid && operator_reply.enabled)
        snprintf(text, sizeof(text), "Last read %.1f C    Candidate %.1f C\nAllowed %.1f .. %.1f C    Revision %d", operator_reply.current / 10.0,
                 operator_candidate / 10.0, operator_reply.minimum / 10.0, operator_reply.maximum / 10.0, operator_reply.revision);
    else snprintf(text, sizeof(text), "Last read --    Candidate --\nNo verified writable parameter range");
    set_text(operator_values, text);
    for(int index = 0; index < 6; index++) {
        int enabled = index == 5 || (!operator_busy && (index == 0 || (operator_valid && operator_reply.enabled && (index != 4 || operator_preview))));
        if(enabled) lv_obj_remove_state(operator_buttons[index], LV_STATE_DISABLED); else lv_obj_add_state(operator_buttons[index], LV_STATE_DISABLED);
    }
}

static void create_operator_ui(lv_obj_t *screen, lv_obj_t *top_bar) {
    operator_socket = getenv("CABINET_OPERATOR_SOCKET");
    if(!operator_socket || !*operator_socket) { operator_socket = NULL; return; }
    operator_group = lv_group_create();
    lv_obj_set_width(header_meta_label, 280);
    operator_open = lv_button_create(top_bar); lv_obj_set_pos(operator_open, 1140, 10); lv_obj_set_size(operator_open, 126, 38);
    lv_obj_t *text = lv_label_create(operator_open); lv_label_set_text(text, "PARAM"); lv_obj_center(text);
    lv_obj_add_event_cb(operator_open, operator_show, LV_EVENT_CLICKED, NULL); lv_group_add_obj(operator_group, operator_open);
    operator_window = panel_styled(screen, 236, 136, 808, 430, PANEL, TEAL, 8);
    operator_title = label(operator_window, 24, 18, 760, &lv_font_montserrat_20, TEXT, preview_mode ? "HOST FIXTURE - NOT HARDWARE" : "PS TEMPERATURE SETPOINT");
    label(operator_window, 24, 58, 760, &lv_font_montserrat_16, MUTED, "No start, protection reset, gain, limit or calibration changes.");
    operator_values = label(operator_window, 24, 104, 760, &lv_font_montserrat_28, TEXT, "Current --    Candidate --");
    lv_obj_set_height(operator_values, 88);
    operator_message = label(operator_window, 24, 218, 760, &lv_font_montserrat_16, AMBER, "Press Refresh. No command has been submitted.");
    lv_label_set_long_mode(operator_message, LV_LABEL_LONG_WRAP); lv_obj_set_height(operator_message, 64);
    const char *names[] = {"Refresh", "-0.1 C", "+0.1 C", "Preview", "Confirm", "Close"};
    for(int index = 0; index < 6; index++) {
        operator_buttons[index] = lv_button_create(operator_window); lv_obj_set_pos(operator_buttons[index], 24 + index * 128, 306); lv_obj_set_size(operator_buttons[index], 118, 44);
        lv_obj_set_style_opa(operator_buttons[index], LV_OPA_40, LV_STATE_DISABLED);
        text = lv_label_create(operator_buttons[index]); lv_obj_set_style_text_font(text, &lv_font_montserrat_16, 0); lv_label_set_text(text, names[index]); lv_obj_center(text);
        lv_obj_add_event_cb(operator_buttons[index], operator_clicked, LV_EVENT_CLICKED, (void *)(uintptr_t)index); lv_group_add_obj(operator_group, operator_buttons[index]);
    }
    label(operator_window, 24, 378, 760, &lv_font_montserrat_16, MUTED, "Runtime only. Restart restores commissioned configuration.");
    lv_obj_add_flag(operator_window, LV_OBJ_FLAG_HIDDEN); operator_refresh();
}

static void operator_shutdown(void) {
    if(operator_created) { pthread_join(operator_thread, NULL); operator_created = 0; }
}

#ifdef CABINET_OPERATOR_TEST
static int operator_test(const char *path) {
    if(!path || !operator_window) return 1;
    FILE *stream = fopen(path, "r"); if(!stream) return 0;
    lv_obj_remove_flag(operator_window, LV_OBJ_FLAG_HIDDEN);
    int action;
    while(fscanf(stream, "%d", &action) == 1) {
        if(action < 0 || action > 5) { fclose(stream); return 0; }
        lv_obj_send_event(operator_buttons[action], LV_EVENT_CLICKED, NULL);
        unsigned long long deadline = parameter_now() + 2000;
        while(operator_busy && parameter_now() < deadline) {
            operator_refresh(); struct timespec delay = {0, 1000000}; nanosleep(&delay, NULL);
        }
        operator_refresh();
        if(operator_busy || !operator_valid) { fclose(stream); return 0; }
        struct timespec delay = {0, 100000000}; nanosleep(&delay, NULL);
    }
    fclose(stream); return 1;
}
#endif
#endif
