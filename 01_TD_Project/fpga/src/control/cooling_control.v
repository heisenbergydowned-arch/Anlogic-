`timescale 1ns/1ps
// Cabinet cooling control/protection subsystem, register ABI FCB1 v1.
// All paths are clk-domain local. FFT/PS/network backpressure never gates it.
module cooling_control #(
    parameter CLK_FREQ=100_000_000, parameter GRACE_MS=4000,
    parameter CONTROL_MS=10, parameter BENCH_ENABLE=1, parameter STARTUP_MS=2000,
    parameter PRESSURE_INDEPENDENT=0
)(
    input wire clk, rst_n,
    input wire adc_new, adc_error, input wire signed [15:0] current_raw, pressure_raw,
    input wire pressure_new, pressure_error,
    input wire temp_new, temp_present, temp_stale, temp_short, input wire signed [15:0] temp_raw,
    input wire fg_new, fg_timeout, input wire [31:0] fg_period, fg_pulses,
    input wire a_new,b_new, input wire signed [15:0] ax,ay,az,bx,by,bz,
    input wire diagnostic_bad, auxiliary_bad,
    input wire [31:0] transport_bad_frames, transport_busy_drops,
    input wire manual_step, local_silence, local_reset, local_permit,
    input wire req, write_en, input wire [15:0] address, input wire [31:0] write_data,
    output wire response, output wire [31:0] read_data, output wire [7:0] error,
    output wire [15:0] applied_duty,
    output wire hard_inhibit, buzzer, red_on, red_flash,
    output wire [31:0] active, latched,
    output wire [1:0] alarm_level,
    output wire [2:0] fan_action,
    output wire [3:0] mode, output wire stable_run,
    output wire [1023:0] monitor_status,
    output wire [767:0] active_config,
    output wire initial_config_permit
);
    wire bench_select=address>=16'h0900 && address<16'h0940;
    wire thermal_select=address>=16'h0a00 && address<16'h0a40;
    wire thermal_response,thermal_armed,thermal_tripped,thermal_selected,thermal_driving;
    wire [7:0] thermal_faults;
    wire [31:0] thermal_fault_sources=(thermal_faults[0] ? 32'h10:0)
        | (thermal_faults[1] ? 32'h20:0) | ((|thermal_faults[3:2]) ? 32'h1:0)
        | (thermal_faults[4] ? 32'h200:0) | (thermal_faults[5] ? 32'h40:0)
        | (thermal_faults[6] ? 32'h1000:0) | (thermal_faults[7] ? 32'h2000:0);
    wire [31:0] base_active;
    wire [31:0] thermal_read_data;wire [7:0] thermal_error;wire [15:0] thermal_duty;
    wire normal_response,bench_response,bench_driving,bench_armed,bench_tripped;
    wire [31:0] normal_read_data,bench_read_data;
    wire [7:0] normal_error,bench_error;
    wire [15:0] bench_duty;
    assign response=normal_response|bench_response|thermal_response;
    reg last_bench_select,last_thermal_select;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin last_bench_select<=0;last_thermal_select<=0;end
        else if(req) begin last_bench_select<=bench_select;last_thermal_select<=thermal_select;end
    end
    assign read_data=last_thermal_select ? thermal_read_data:(last_bench_select ? bench_read_data:normal_read_data);
    assign error=thermal_response ? thermal_error:(bench_response ? bench_error:normal_error);
    wire tick_ms;
    wire [31:0] now_ms;
    cooling_tick #(.CLK_FREQ(CLK_FREQ)) u_time(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.now_ms(now_ms));
    wire [767:0] cfg;
    assign active_config=cfg;
    wire cfg_changed;
    wire [31:0] cmd_id,cmd_data;
    wire [7:0] command,last_command_status,last_config_status;
    wire accepted_command;
    reg command_fire;
    reg [7:0] applied_command;
    reg [31:0] applied_command_data;
    wire [31:0] last_command_id;
    reg [7:0] command_status;
    wire [1023:0] status;
    assign monitor_status=status;
    wire [255:0] event_head;
    wire configured=cfg[3:0]==4'hf && cfg[32 +:32]!=0;

    wire [15:0] rpm;
    wire rpm_new,rpm_valid;
    wire [31:0] rpm_age,rejected_periods;
    rpm_measure #(.CLK_FREQ(CLK_FREQ)) u_rpm(.clk(clk),.rst_n(rst_n),.cfg_changed(cfg_changed),
        .tick_ms(tick_ms),.cfg(cfg),.period_count(fg_period),.period_new(fg_new),.fg_timeout(fg_timeout),
        .rpm(rpm),.rpm_new(rpm_new),.valid(rpm_valid),.age_ms(rpm_age),.rejected_periods(rejected_periods));
    wire adc_valid,temp_valid,pressure_valid;
    wire [31:0] adc_age,temp_age,rules,fast_trip;
    wire [16:0] current_magnitude;
    safety_monitor #(.PRESSURE_INDEPENDENT(PRESSURE_INDEPENDENT)) u_safety(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.now_ms(now_ms),.cfg(cfg),
        .adc_new(adc_new),.adc_error(adc_error),.current_raw(current_raw),.pressure_raw(pressure_raw),
        .pressure_new(pressure_new),.pressure_error(pressure_error),
        .temp_new(temp_new),.temp_present(temp_present),.temp_stale(temp_stale),.temp_short(temp_short),.temp_raw(temp_raw),
        .rpm(rpm),.rpm_new(rpm_new),.rpm_valid(rpm_valid),
        .a_new(a_new),.b_new(b_new),.ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),
        .adc_valid(adc_valid),.temp_valid(temp_valid),.pressure_valid(pressure_valid),
        .adc_age_ms(adc_age),.temp_age_ms(temp_age),.current_magnitude(current_magnitude),
        .rule_active(rules),.fast_trip(fast_trip));

    reg ps_owned,ps_run,hb_seen,soft_seen;
    reg [31:0] hb_age,cmd_age,soft_age,manual_age;
    reg [15:0] requested_rpm,ramped_rpm,manual_duty;
    reg [2:0] manual_index;
    reg manual_timed,manual_expired;
    reg [1:0] soft_level;
    reg soft_physical;
    reg [15:0] soft_source;
    reg target_changed;
    wire hb_good=hb_seen && hb_age<cfg[17*32 +:16];
    wire target_good=ps_owned && cmd_age<cfg[17*32+16 +:16];
    wire soft_good=soft_seen && hb_good && soft_age<cfg[20*32+16 +:16];
    wire manual_live=manual_timed && !manual_expired;
    wire local_owner=manual_live || !ps_owned;
    wire unqualified_hold=!BENCH_ENABLE && !configured;
    wire force_fallback=(ps_owned && (!hb_good || !target_good)) || manual_expired;
    wire stop_permit=local_permit && temp_valid && !rules[2] && !rules[3] && !latched[3];
    wire requested_run=local_owner ? manual_duty!=0:ps_run;
    wire desired_run=!unqualified_hold && (requested_run || force_fallback || rules[2] || rules[3] || latched[3]);
    reg grace_done;
    // CSR validation/response is one cycle; actuator side effects use a
    // registered accepted command on the following edge. Payload is captured
    // with acceptance, independent of later writes to the staging registers.
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin command_fire<=0;applied_command<=0;applied_command_data<=0;end
        else begin
            command_fire<=accepted_command;
            if(accepted_command) begin applied_command<=command;applied_command_data<=cmd_data;end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) grace_done<=0;
        else if(now_ms>=GRACE_MS) grace_done<=1;
    end

    // A four-wire fan may keep rotating with a zero PWM command. Confirm
    // actual output zero, never physical power disconnection or stopped FG.
    reg [31:0] previous_pulses,quiet_age,output_zero_age,stopping_at;
    reg previous_run;
    wire [31:0] stopping_age=now_ms-stopping_at;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin previous_pulses<=0;quiet_age<=0;output_zero_age<=0;stopping_at<=0;previous_run<=0;end
        else begin
            previous_run<=requested_run;
            if(previous_run && !requested_run) stopping_at<=now_ms;
            previous_pulses<=fg_pulses;
            if(fg_pulses!=previous_pulses)quiet_age<=0;
            else if(tick_ms && quiet_age!=32'hffff_ffff)quiet_age<=quiet_age+1'b1;
            if(applied_duty!=0 || cfg_changed)output_zero_age<=0;
            else if(tick_ms && output_zero_age!=32'hffff_ffff)output_zero_age<=output_zero_age+1'b1;
        end
    end
    wire output_zero_confirmed=applied_duty==0 && output_zero_age>=cfg[16*32 +:16];
    // Keep the unconfigured diagnostic mode contract used by saved NPU models.
    // Qualified STOP confirms output-zero; neither path claims power removal.
    wire stopping_confirmed=configured ? output_zero_confirmed:(quiet_age>=cfg[16*32 +:16]);
    wire starting;
    wire fg_loss;
    wire drive_inhibited=|(latched & 32'h0000_0b81) || |(rules & 32'h0000_0b01);
    wire need_feedback=grace_done && desired_run && !starting && mode!=0 && !drive_inhibited;
    fault_filter u_fg_loss(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(1'b1),.sample(tick_ms),.valid(1'b1),
        .enter_cond(need_feedback && !rpm_valid),.recover_cond(rpm_valid || !desired_run || drive_inhibited),
        .now_ms(now_ms),.enter_ms(16'd0),.recover_ms(cfg[14*32+16 +:16]),.active(fg_loss));

    reg [15:0] control_count;
    reg control_step;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin control_count<=0;control_step<=0;end
        else begin
            control_step<=0;
            if(tick_ms) begin
                if(control_count==CONTROL_MS-1) begin control_count<=0;control_step<=1;end
                else control_count<=control_count+1'b1;
            end
        end
    end
    wire [16:0] target_error=requested_rpm>rpm ? requested_rpm-rpm:rpm-requested_rpm;
    wire tracking_ok=rpm_valid && target_error<=cfg[12*32+16 +:16];
    wire pi_saturated;
    wire [15:0] pi_duty;
    reg pi_enable;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) pi_enable<=0;
        else pi_enable<=configured && ps_owned && ps_run && hb_good && target_good && !local_owner
            && !force_fallback && !fg_loss && latched==0 && !(|rules) && adc_valid && temp_valid && rpm_valid;
    end
    rpm_pi u_pi(.clk(clk),.rst_n(rst_n),.enable(pi_enable),.step(control_step),
        .target_rpm(ramped_rpm),.rpm(rpm),.rpm_new(rpm_new),.rpm_valid(rpm_valid),.applied_duty(applied_duty),
        .duty_min(cfg[4*32 +:16]),.duty_max(cfg[4*32+16 +:16]),
        .kp_q8(cfg[6*32 +:16]),.ki_q8(cfg[6*32+16 +:16]),.duty(pi_duty),.saturated(pi_saturated));
    wire tracking_fault;
    fault_filter u_tracking(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(ps_owned && cfg[3]),.sample(rpm_new),.valid(rpm_valid),
        .enter_cond(mode==3 && pi_enable && pi_saturated && !tracking_ok),.recover_cond(tracking_ok),
        .now_ms(now_ms),.enter_ms(cfg[19*32 +:16]),.recover_ms(cfg[14*32+16 +:16]),.active(tracking_fault));

    wire current_lost=grace_done && desired_run && (!adc_valid || (!temp_valid && !cfg[2]));
    wire temperature_lost=grace_done && desired_run && !temp_valid;
    wire vibration_rail=ax==16'sh8000 || ax==16'sh7fff || ay==16'sh8000 || ay==16'sh7fff || az==16'sh8000 || az==16'sh7fff
        || bx==16'sh8000 || bx==16'sh7fff || by==16'sh8000 || by==16'sh7fff || bz==16'sh8000 || bz==16'sh7fff;
    wire diag_lost=grace_done && (diagnostic_bad || vibration_rail || !pressure_valid);
    wire aux_lost=grace_done && auxiliary_bad;
    wire stall=fg_loss && rules[1] && !starting;
    assign active=base_active|thermal_fault_sources;
    assign base_active=rules | (current_lost ? 32'h10:0) | (temperature_lost ? 32'h20:0)
        | (fg_loss ? 32'h40:0) | (stall ? 32'h100:0)
        | ((ps_owned && !hb_good) ? 32'h1000:0) | (((ps_owned && !target_good) || manual_expired) ? 32'h2000:0)
        | (diag_lost ? 32'h4000:0) | (aux_lost ? 32'h8000:0) | (!configured ? 32'h10000:0)
        | (tracking_fault ? 32'h20000:0)
        | ((!requested_run && !stopping_confirmed && mode==5 && stopping_age>=cfg[16*32 +:16]) ? 32'h40000:0)
        | ((soft_good && soft_level!=0) ? 32'h80000:0)
        | ((soft_seen && !soft_good) ? 32'h100000:0);
    wire reset_safe=adc_valid && temp_valid && (!cfg[0] || current_magnitude<=cfg[8*32+16 +:16])
        && (!cfg[1] || $signed(temp_raw)<=$signed(cfg[10*32 +:16])) && (rules & 32'h0000_0f0f)==0
        && !current_lost && !temperature_lost;
    wire reset_accepted,reset_rejected;
    protect_fsm u_fsm(.clk(clk),.rst_n(rst_n),.now_ms(now_ms),.cfg(cfg),.grace_done(grace_done),
        .desired_run(desired_run),.local_owner(local_owner),
        .degraded(force_fallback || fg_loss || !configured || !adc_valid || !temp_valid),
        .feedback_valid(rpm_valid),.stopping_confirmed(stopping_confirmed),
        .target_changed(target_changed),.tracking_ok(tracking_ok),.active(base_active),
        .local_reset(local_reset),.reset_safe(reset_safe),.mode(mode),.latched(latched),
        .reset_accepted(reset_accepted),.reset_rejected(reset_rejected),.starting(starting),.stable_run(stable_run));

    // PI must never reuse its tracked zero during startup: the startup output
    // is explicit until the first valid feedback; overrides own final duty.
    wire [15:0] normal_duty=local_owner ? manual_duty:
        (!ps_run ? 16'd0:(!pi_enable ? cfg[2*32 +:16]:pi_duty));
    wire cooling_lost;
    wire arbiter_inhibit;
    wire [2:0] arbiter_action;
    wire [15:0] arbiter_duty;
    reg [15:0] duty_register;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) duty_register<=BENCH_ENABLE ? 2000:0;
        else duty_register<=arbiter_duty;
    end
    assign applied_duty=thermal_selected ? thermal_duty:(bench_driving ? bench_duty:(hard_inhibit ? 16'd0:duty_register));
    // With bench output disabled, unqualified coefficients must not silently
    // select an unvalidated default fallback. Zero PWM is only signal inhibit.
    assign hard_inhibit=thermal_selected ? (!thermal_driving || thermal_duty==0):(!bench_driving && (arbiter_inhibit || unqualified_hold));
    assign fan_action=thermal_selected ? (hard_inhibit ? 3'd3:3'd6):(bench_driving ? 3'd6:(unqualified_hold ? 3'd3:arbiter_action));
    control_arbiter u_arbiter(.cfg(cfg),.active(base_active),.latched(latched),.normal_duty(normal_duty),
        .normal_action(local_owner ? 3'd6:(!ps_run ? 3'd5:(!pi_enable ? 3'd7:3'd0))),
        .force_fallback(force_fallback),.off_allowed(!requested_run && stop_permit),
        .applied_duty(arbiter_duty),.fan_action(arbiter_action),
        .inhibit(arbiter_inhibit),.cooling_lost(cooling_lost));

    wire [31:0] all_sources=active|latched;
    wire severe=|(all_sources & 32'h0000_0b19); // OC,thermal,current lost,stall,overspeed,vib hard
    wire physical_l2=|(all_sources & 32'h0002_30e6); // current/thermal/FG/start/PS/lease/tracking
    wire [1:0] physical_level=severe ? 3:(physical_l2 ? 2:(all_sources!=0 ? 1:0));
    assign alarm_level=soft_good && soft_level>physical_level ? soft_level:physical_level;
    wire [1:0] audible_level=(soft_good && soft_physical && soft_level>physical_level) ? soft_level:
        (severe ? 3:(physical_l2 ? 2:0));
    wire silenced;
    alarm_outputs u_alarm(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.level(alarm_level),.audible_level(audible_level),
        .sources(all_sources),.local_silence(local_silence),.silence_ms(cfg[20*32 +:16]),
        .buzzer(buzzer),.red_flash(red_flash),.red_on(red_on),.silenced(silenced));

    reg [31:0] event_seq,seen_sources,lost_events;
    reg [1:0] peak_level;
    reg acknowledged;
    reg [31:0] previous_active,previous_latched;
    reg [15:0] previous_meta;
    reg [255:0] events[0:7];
    reg [2:0] q_write,q_read;
    reg [3:0] q_count;
    wire test_mode=local_owner || !configured;
    wire [15:0] meta={2'd0,test_mode,acknowledged,silenced,2'd0,fan_action,mode,alarm_level};
    wire event_change=active!=previous_active || latched!=previous_latched || meta!=previous_meta;
    wire pop_event=command_fire && applied_command==8;
    // Two reserved slots: ordinary L1 traffic cannot occupy the L2/L3 slots.
    // Overflow of repeated high-priority revisions is observable, while the
    // live/latched/seen/peak summary always retains the physical causes.
    wire [3:0] queue_limit=alarm_level==3 ? 8:(alarm_level==2 ? 7:6);
    wire push_event=event_change && (q_count<queue_limit || pop_event);
    assign event_head=q_count==0 ? 256'd0:events[q_read];
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            event_seq<=0;seen_sources<=0;lost_events<=0;peak_level<=0;acknowledged<=0;
            previous_active<=0;previous_latched<=0;previous_meta<=0;q_write<=0;q_read<=0;q_count<=0;
        end else begin
            previous_active<=active;previous_latched<=latched;previous_meta<=meta;
            seen_sources<=seen_sources|all_sources;
            if(alarm_level>peak_level) peak_level<=alarm_level;
            if(command_fire && applied_command==4) acknowledged<=1;
            if((all_sources & ~(previous_active|previous_latched))!=0 || alarm_level>previous_meta[1:0]) acknowledged<=0;
            if(event_change) event_seq<=event_seq+1'b1;
            if(event_change && !push_event && lost_events!=32'hffff_ffff) lost_events<=lost_events+1'b1;
            if(push_event) begin
                events[q_write]<={lost_events,cfg[32 +:32],all_sources^(previous_active|previous_latched),
                    16'd0,meta,latched,active,now_ms,event_seq+1'b1};
                q_write<=q_write+1'b1;
            end
            if(pop_event) q_read<=q_read+1'b1;
            case({push_event,pop_event})
                2'b10:q_count<=q_count+1'b1;
                2'b01:q_count<=q_count-1'b1;
                default:q_count<=q_count;
            endcase
        end
    end

    // Strict virgin commissioning is separate from a physical key permit.
    // Snapshot7 and event ACKs may read this eligibility without suppressing it.
    wire initial_control_command=(accepted_command && (command==1 || command==2 || command==3))
        || (command_fire && (applied_command==1 || applied_command==2 || applied_command==3));
    assign initial_config_permit=rst_n && cfg[31:0]==0 && cfg[32 +:32]==0
        && !ps_owned && !ps_run && !manual_live && !manual_timed && !manual_expired
        && manual_duty==0 && !manual_step && requested_rpm==0 && ramped_rpm==0
        && !bench_armed && !bench_driving && !thermal_selected && applied_duty==0 && latched==0
        && adc_valid && temp_valid && !cfg_changed && !initial_control_command;
    // Already configured maintenance keeps KEY/owner guards and requires sustained actual PWM zero.
    wire commit_allowed=!bench_armed && !thermal_selected && local_owner && latched==0
        && ((local_permit && (cfg[4:0]==0 || (!desired_run && output_zero_confirmed && stop_permit)))
            || initial_config_permit);
    always @* begin
        command_status=0;
        case(command)
            1:begin
                if(cmd_data[31:16]!=0 || cmd_data[15:0]<cfg[5*32 +:16] || cmd_data[15:0]>cfg[5*32+16 +:16]) command_status=2;
                else if(!configured) command_status=2;
                else if(latched!=0) command_status=6;
                else if(!adc_valid || !temp_valid) command_status=5;
                else if(!hb_good) command_status=7;
                else if(manual_live) command_status=8;
            end
            2:begin
                if(cmd_data!=0 || !stop_permit) command_status=3;
                else if(!hb_good) command_status=7;
                else if(manual_live) command_status=8;
            end
            3:if(cmd_data!=0) command_status=1;
            4:if(cmd_data!=event_seq) command_status=4;
            5:begin
                if(cmd_data[15:8]!=1 || (cmd_data[7:0] & 8'hec)!=0 || (cmd_data[1:0]!=0 && cmd_data[31:16]==0)) command_status=2;
                else if(!hb_good) command_status=7;
            end
            7:if(cmd_data!=0) command_status=1;
            8:if(q_count==0 || cmd_data!=event_head[31:0]) command_status=4;
            default:command_status=3; // No remote RESET or SILENCE opcodes.
        endcase
        // A COMMIT revokes old leases on the next edge. Do not accept a target
        // or heartbeat in that edge using the pre-COMMIT heartbeat state.
        if(cfg_changed && (command==1 || command==2 || command==3))command_status=5;
    end
    cooling_regs #(.STARTUP_MS(STARTUP_MS)) u_regs(.clk(clk),.rst_n(rst_n),.req(req && !bench_select && !thermal_select),.write_en(write_en),.address(address),.write_data(write_data),
        .response(normal_response),.read_data(normal_read_data),.error(normal_error),.local_permit(local_permit),.initial_config_permit(initial_config_permit),.commit_allowed(commit_allowed),
        .live_status(status),.event_head(event_head),.command_status(command_status),.command_fire(accepted_command),
        .command(command),.command_id(cmd_id),.command_data(cmd_data),.cfg(cfg),.cfg_changed(cfg_changed),
        .last_command_status(last_command_status),.last_config_status(last_config_status),.last_command_id(last_command_id));

    // Bench may own output only before full commissioning and while the
    // production owner and local manual controls are idle. Hardware fault
    // latches still revoke it; it does not set any qualification flags.
    commission_bench u_commission_bench(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),
        .local_permit(local_permit),.idle_allowed(!configured && !ps_run && !manual_live && !thermal_selected && latched==0),
        .adc_valid(adc_valid),.temp_valid(temp_valid),.fg_new(fg_new),
        .current_raw(current_raw),.temp_raw(temp_raw),.fg_period(fg_period),
        .req(req && bench_select),.write_en(write_en),.address(address[7:0]),.write_data(write_data),
        .response(bench_response),.read_data(bench_read_data),.error(bench_error),
        .driving(bench_driving),.duty(bench_duty),.armed(bench_armed),.tripped(bench_tripped));

    temperature_pwm u_temperature_pwm(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),
        .idle_allowed(!configured && !ps_run && !manual_live && manual_duty==0 && !manual_step && !bench_armed && latched==0),
        .adc_new(adc_new),.adc_valid(adc_valid),.temp_valid(temp_valid && temp_age<=2000),
        .rpm_valid(rpm_valid),.current_raw(current_raw),.temp_raw(temp_raw),.rpm(rpm),
        .req(req && thermal_select),.write_en(write_en),.address(address[7:0]),.write_data(write_data),
        .response(thermal_response),.read_data(thermal_read_data),.error(thermal_error),
        .armed(thermal_armed),.tripped(thermal_tripped),.selected(thermal_selected),
        .driving(thermal_driving),.duty(thermal_duty),.fault_causes(thermal_faults));

    function [15:0] index_duty;
        input [2:0] index;
        begin case(index) 0:index_duty=0;1:index_duty=1000;2:index_duty=2000;3:index_duty=3000;default:index_duty=4000;endcase end
    endfunction
    wire [2:0] next_index=manual_index==4 ? 0:manual_index+1'b1;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            ps_owned<=0;ps_run<=0;hb_seen<=0;soft_seen<=0;
            hb_age<=32'hffff_ffff;cmd_age<=32'hffff_ffff;soft_age<=32'hffff_ffff;manual_age<=0;
            requested_rpm<=0;ramped_rpm<=0;manual_duty<=BENCH_ENABLE ? 2000:0;manual_index<=2;
            manual_timed<=0;manual_expired<=0;soft_level<=0;soft_physical<=0;soft_source<=0;target_changed<=0;
        end else begin
            target_changed<=0;
            if(tick_ms) begin
                if(hb_age!=32'hffff_ffff) hb_age<=hb_age+1'b1;
                if(cmd_age!=32'hffff_ffff) cmd_age<=cmd_age+1'b1;
                if(soft_age!=32'hffff_ffff) soft_age<=soft_age+1'b1;
                if(manual_timed && manual_age!=32'hffff_ffff) manual_age<=manual_age+1'b1;
                if(manual_timed && manual_age>=cfg[16*32+16 +:16]) manual_expired<=1;
            end
            if(control_step && ps_owned && ps_run && target_good && hb_good) begin
                if(ramped_rpm<requested_rpm) begin
                    if(requested_rpm-ramped_rpm>cfg[12*32 +:16]) ramped_rpm<=ramped_rpm+cfg[12*32 +:16];
                    else ramped_rpm<=requested_rpm;
                end else if(ramped_rpm>requested_rpm) begin
                    if(ramped_rpm-requested_rpm>cfg[12*32 +:16]) ramped_rpm<=ramped_rpm-cfg[12*32 +:16];
                    else ramped_rpm<=requested_rpm;
                end
            end
            if(command_fire) begin
                case(applied_command)
                    1:begin
                        manual_timed<=0;manual_expired<=0;manual_age<=0;
                        if(!ps_owned) ramped_rpm<=rpm_valid ? rpm:cfg[5*32 +:16];
                        ps_owned<=1;ps_run<=1;requested_rpm<=applied_command_data[15:0];cmd_age<=0;
                        target_changed<=requested_rpm!=applied_command_data[15:0];
                    end
                    2:begin ps_owned<=1;ps_run<=0;requested_rpm<=0;ramped_rpm<=0;cmd_age<=0;manual_timed<=0;manual_expired<=0;manual_age<=0;end
                    3:begin hb_seen<=1;hb_age<=0;end
                    5:begin soft_seen<=1;soft_age<=0;soft_level<=applied_command_data[1:0];soft_physical<=applied_command_data[4];soft_source<=applied_command_data[31:16];end
                    default:begin end
                endcase
            end
            if(manual_step && !thermal_selected && (BENCH_ENABLE || local_permit) && (!ps_owned || local_permit)) begin
                if(next_index!=0 || stop_permit) begin manual_index<=next_index;manual_duty<=index_duty(next_index);end
                manual_age<=0;manual_timed<=1;manual_expired<=0;
            end
            // A local action always wins that clock. Configuration invalidates
            // remote leases/results; a fresh heartbeat and target are required.
            if(cfg_changed) begin
                hb_seen<=0;cmd_age<=32'hffff_ffff;soft_seen<=0;
                manual_timed<=0;manual_expired<=0;ps_owned<=0;ps_run<=0;
            end
        end
    end

    assign status[0*32 +:32]={9'd0,1'b1,output_zero_confirmed,initial_config_permit,1'b1,test_mode,reset_rejected,reset_accepted,local_permit,configured,
        pressure_valid,temp_valid,adc_valid,rpm_valid,hb_good,target_good,manual_live,soft_good,stable_run,
        hard_inhibit,cooling_lost,pi_saturated,acknowledged,silenced};
    assign status[1*32 +:32]=now_ms;
    assign status[2*32 +:32]={16'd0,meta};
    assign status[3*32 +:32]=active;
    assign status[4*32 +:32]=latched;
    assign status[5*32 +:32]=seen_sources;
    assign status[6*32 +:32]={30'd0,peak_level};
    assign status[7*32 +:32]={manual_duty,applied_duty};
    assign status[8*32 +:32]={requested_rpm,rpm};
    assign status[9*32 +:32]={ramped_rpm,pi_duty};
    assign status[10*32 +:32]=adc_age;
    assign status[11*32 +:32]=temp_age;
    assign status[12*32 +:32]=rpm_age;
    assign status[13*32 +:32]=hb_age;
    assign status[14*32 +:32]=cmd_age;
    assign status[15*32 +:32]=event_seq;
    assign status[16*32 +:32]=lost_events;
    assign status[17*32 +:32]={28'd0,q_count};
    assign status[18*32 +:32]=cfg[32 +:32];
    assign status[19*32 +:32]=last_command_id;
    assign status[20*32 +:32]={16'd0,last_config_status,last_command_status};
    assign status[21*32 +:32]={15'd0,current_magnitude};
    assign status[22*32 +:32]={pressure_raw,current_raw};
    assign status[23*32 +:32]={16'd0,temp_raw};
    assign status[24*32 +:32]=fg_period;
    assign status[25*32 +:32]=fg_pulses;
    assign status[26*32 +:32]=quiet_age; // Retained FG quiet-age contract, never power-off proof.
    assign status[27*32 +:32]=rejected_periods;
    assign status[28*32 +:32]=transport_bad_frames;
    assign status[29*32 +:32]=transport_busy_drops;
    assign status[30*32 +:32]=soft_age;
    assign status[31*32 +:32]={soft_source,13'd0,soft_physical,2'd0};
endmodule
