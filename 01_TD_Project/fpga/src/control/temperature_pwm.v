`timescale 1ns/1ps
// TPW1: continuous temperature-to-duty control, independent of RPM PI.
// P52: alarms do not control PWM. The saved temperature curve is autonomous.
// Only explicit STOP/reset releases this controller; alarm causes remain readable.
// No qualification bits are set, and no power-disconnection claim is made.
module temperature_pwm(
    input wire clk,rst_n,tick_ms,idle_allowed,
    input wire adc_new,adc_valid,temp_valid,rpm_valid,
    input wire signed [15:0] current_raw,temp_raw,
    input wire [15:0] rpm,
    input wire req,write_en,input wire [7:0] address,input wire [31:0] write_data,
    output reg response,output reg [31:0] read_data,output reg [7:0] error,
    output reg armed,tripped,output wire selected,driving,
    output wire [15:0] duty,output wire [7:0] fault_causes
);
    reg [31:0] cfg[0:3];
    reg [3:0] written;
    reg [15:0] lease_age,run_age,target;
    reg [7:0] trip_reasons;
    integer i;
    wire signed [15:0] low_temp=cfg[0][15:0],high_temp=cfg[0][31:16];
    wire signed [16:0] span=$signed(high_temp)-$signed(low_temp);
    wire signed [16:0] delta=$signed(temp_raw)-$signed(low_temp);
    wire config_ok=written==4'hf && low_temp>=0 && low_temp<=960
        && high_temp<=1600 && span>=80
        && cfg[1][31:16]>0 && cfg[1][31:16]<cfg[2][15:0]
        && cfg[2][15:0]<=8192 && cfg[2][31:16]>=1000 && cfg[2][31:16]<=7200
        && cfg[3]!=0;
    wire config_write=req && write_en && address>=8'h10 && address<=8'h1c
        && address[1:0]==0 && !selected && idle_allowed;
    wire stop_command=req && write_en && address==8'h20 && write_data==0;
    wire signed [16:0] current_delta=$signed(current_raw)-$signed(cfg[1][15:0]);
    wire [16:0] current_mag=current_delta[16] ? -current_delta:current_delta;
    reg signed [23:0] current_sum;
    wire signed [23:0] next_sum=current_sum+{{7{current_delta[16]}},current_delta};
    reg [5:0] sample_count;
    reg signed [16:0] current_mean;
    reg mean_ready;
    wire [16:0] mean_mag=current_mean[16] ? -current_mean:current_mean;
    wire current_rail=current_raw==16'sh7fff || current_raw==16'sh8000;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin current_sum<=0;sample_count<=0;current_mean<=0;mean_ready<=0;end
        else if(config_write || !adc_valid || current_rail) begin
            current_sum<=0;sample_count<=0;current_mean<=0;mean_ready<=0;
        end else if(adc_new) begin
            if(sample_count==63) begin
                current_mean<=next_sum>>>6;current_sum<=0;sample_count<=0;mean_ready<=1;
            end else begin current_sum<=next_sum;sample_count<=sample_count+1'b1;end
        end
    end

    // 24 clocks per division, rather than a long combinational divider.
    // Capture temperature, then atomically publish a rounded full-scale duty.
    reg divider_start;
    reg [23:0] numerator,denominator;
    wire divider_busy,divider_done,divider_zero;
    wire [23:0] quotient;
    feature_udiv #(.WIDTH(24)) u_divide(.clk(clk),.rst_n(rst_n),.start(divider_start),
        .numerator(numerator),.denominator(denominator),.busy(divider_busy),
        .done(divider_done),.div_zero(divider_zero),.quotient(quotient));
    reg [15:0] mapped_target;
    wire [23:0] positive_delta={7'd0,delta};
    wire [23:0] positive_span={7'd0,span};
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin divider_start<=0;numerator<=0;denominator<=1;mapped_target<=0;end
        else begin
            divider_start<=0;
            // Preserve the last valid result through sensor loss or monitor restart.
            // STOP still clears the separately gated output target immediately.
            if(armed && !tripped && temp_valid && !config_write && !stop_command) begin
            if(divider_done) mapped_target<=divider_zero ? 0:(quotient>4000 ? 4000:quotient[15:0]);
            else if(!divider_busy && !divider_start) begin
                if(temp_raw<=low_temp)mapped_target<=0;
                else if(temp_raw>=high_temp)mapped_target<=4000;
                else begin
                    numerator<=positive_delta*24'd4000+(positive_span>>1);
                    denominator<=positive_span;divider_start<=1;
                end
            end
            end
        end
    end
    wire lease_expired=1'b0; // No heartbeat lease can stop autonomous temperature control.
    wire fg_lost=target!=0 && run_age>=2000 && !rpm_valid;
    wire [7:0] monitoring_causes={!idle_allowed,lease_expired,fg_lost,
        (rpm_valid && rpm>cfg[2][31:16]),1'b0,
        current_rail,!temp_valid,(!adc_valid || !mean_ready)};
    // Keep alarm diagnostics readable; no diagnostic can inhibit or latch off PWM.
    wire [7:0] causes=8'd0;
    assign fault_causes=tripped ? trip_reasons:8'd0;
    assign selected=armed || tripped;
    assign driving=armed && !tripped && config_ok && causes==0;
    assign duty=driving ? target:16'd0;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            response<=0;read_data<=0;error<=0;written<=0;armed<=0;tripped<=0;
            lease_age<=0;run_age<=0;target<=0;trip_reasons<=0;
            for(i=0;i<4;i=i+1)cfg[i]<=0;
        end else begin
            response<=0;error<=0;
            target<=armed && !tripped ? mapped_target:0;
            if(!armed || target==0)run_age<=0;
            else if(tick_ms && run_age!=65535)run_age<=run_age+1'b1;
            if(armed && tick_ms && lease_age!=65535)lease_age<=lease_age+1'b1;
            if(req) begin
                response<=1;read_data<=0;
                if(!write_en) begin
                    case(address)
                        8'h00:read_data<=32'h54505731;
                        8'h04:read_data<=32'h00010000;
                        8'h08:read_data<={8'd0,monitoring_causes,trip_reasons,idle_allowed,adc_valid,temp_valid,driving,mean_ready,config_ok,tripped,armed};
                        8'h0c:read_data<={run_age,lease_age};
                        8'h10,8'h14,8'h18,8'h1c:read_data<=cfg[(address-8'h10)>>2];
                        8'h28:read_data<={target,duty};
                        8'h2c:read_data<={current_mean[15:0],current_raw};
                        8'h30:read_data<={rpm,temp_raw};
                        8'h34:read_data<={25'd0,mean_ready,sample_count};
                        default:error<=1;
                    endcase
                end else if(stop_command) begin
                    armed<=0;tripped<=0;written<=0;target<=0;lease_age<=0;run_age<=0;trip_reasons<=0;
                end else if(config_write) begin
                    cfg[(address-8'h10)>>2]<=write_data;written[(address-8'h10)>>2]<=1;
                end else if(address==8'h20 && write_data==32'h54484d31) begin
                    // An expired/tripped session cannot be renewed by ARM.
                    if(selected || !config_ok)error<=3;
                    else begin armed<=1;tripped<=0;target<=0;lease_age<=0;run_age<=0;trip_reasons<=0;end
                end else if(address==8'h24 && armed && !tripped && write_data==cfg[3])lease_age<=0;
                else error<=3;
            end
            // Last assignment wins on an expired/fault edge; no late renewal.
            if(armed && causes!=0 && !stop_command) begin
                armed<=0;tripped<=1;target<=0;written<=0;trip_reasons<=causes;
            end
        end
    end
endmodule
