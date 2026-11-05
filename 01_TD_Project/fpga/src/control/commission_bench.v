`timescale 1ns/1ps
// BNC register block ABI2: explicitly authorized remote finite commissioning.
// local_permit remains an independent qualified-control / physical-key signal;
// this isolated bench accepts only the versioned ARM2 operation.
// Values are operator-reviewed limits, never defaults or PI qualifications.
module commission_bench(
    input wire clk,rst_n,tick_ms,local_permit,idle_allowed,
    input wire adc_valid,temp_valid,fg_new,
    input wire signed [15:0] current_raw,temp_raw,
    input wire [31:0] fg_period,
    input wire req,write_en,input wire [7:0] address,input wire [31:0] write_data,
    output reg response,output reg [31:0] read_data,output reg [7:0] error,
    output wire driving,output wire [15:0] duty,output reg armed,output reg tripped
);
    reg [31:0] limits[0:5];
    reg [5:0] written;
    reg [15:0] requested,elapsed,lease_age;
    reg [3:0] unhealthy_ms;
    reg unhealthy_tick_seen,fg_seen;
    reg [31:0] last_fg_period;
    reg [7:0] health_reasons,trip_reasons;
    integer i;
    wire signed [16:0] distance=$signed(current_raw)-$signed(limits[1][15:0]);
    wire [16:0] magnitude=distance<0 ? -distance:distance;
    // Keep the latest FG assessment between pulses; a one-cycle fg_new must
    // not defeat the continuous unhealthy confirmation timer.
    wire overspeed=(fg_new || fg_seen) && (fg_new ? fg_period:last_fg_period)<limits[4];
    wire valid_limits=written==6'h3f && limits[0]>0 && limits[0]<=4000
        && limits[1][31:16]==0 && limits[2]>0 && limits[2]<=65535
        && limits[3][31:16]==0 && $signed(limits[3][15:0])>=-880 && $signed(limits[3][15:0])<=2000
        && limits[4]>=128 && limits[5]>0 && limits[5]<=30000;
    wire healthy=adc_valid && temp_valid && magnitude<limits[2]
        && temp_raw<$signed(limits[3][15:0]) && !overspeed;
    wire lease_expired=lease_age>=500,duration_expired=elapsed>=limits[5];
    wire [7:0] causes={!idle_allowed,!adc_valid,!temp_valid,magnitude>=limits[2],
        temp_raw>=$signed(limits[3][15:0]),overspeed,lease_expired,duration_expired};
    wire health_confirmed=!healthy && (unhealthy_ms>=10
        || (tick_ms && unhealthy_tick_seen && unhealthy_ms>=9));
    wire authorized=armed && !tripped && idle_allowed && !lease_expired && !duration_expired;
    // A short unhealthy interval immediately inhibits PWM. Only the persistent
    // trial latch waits for >=10 complete millisecond intervals (10..11ms
    // from an arbitrary onset). Valid renewed requests never bypass this gate.
    assign driving=authorized && healthy;
    assign duty=driving ? requested:16'd0;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            response<=0;read_data<=0;error<=0;written<=0;armed<=0;tripped<=0;
            requested<=0;elapsed<=0;lease_age<=0;
            unhealthy_ms<=0;unhealthy_tick_seen<=0;health_reasons<=0;trip_reasons<=0;
            fg_seen<=0;last_fg_period<=0;
            for(i=0;i<6;i=i+1) limits[i]<=0;
        end else begin
            response<=0;error<=0;
            if(fg_new)begin fg_seen<=1;last_fg_period<=fg_period;end
            if(!armed || healthy)begin unhealthy_ms<=0;unhealthy_tick_seen<=0;health_reasons<=0;end
            else begin
                health_reasons<=health_reasons | (causes & 8'h7c);
                if(tick_ms)begin
                    if(!unhealthy_tick_seen)unhealthy_tick_seen<=1;
                    else if(unhealthy_ms<10)unhealthy_ms<=unhealthy_ms+1'b1;
                end
            end
            if(armed && tick_ms) begin
                if(elapsed!=65535) elapsed<=elapsed+1'b1;
                if(lease_age!=65535) lease_age<=lease_age+1'b1;
            end
            if(req) begin
                response<=1;read_data<=0;
                if(!write_en) begin
                    case(address)
                        8'h00:read_data<=32'h424e4331;
                        8'h04:read_data<=32'h00020000;
                        8'h08:read_data<={trip_reasons,21'd0,valid_limits,tripped,armed};
                        8'h0c:read_data<={lease_age,elapsed};
                        8'h34:read_data<={16'd0,duty};
                        default:if(address>=8'h10 && address<=8'h24 && address[1:0]==0)
                            read_data<=limits[(address-8'h10)>>2];else error<=1;
                    endcase
                end else if(address==8'h30 && write_data==0) begin
                    armed<=0;requested<=0;written<=0; // New arm needs a freshly installed profile.
                end else if(address>=8'h10 && address<=8'h24 && address[1:0]==0) begin
                    if(armed || !idle_allowed) error<=3;
                    else begin limits[(address-8'h10)>>2]<=write_data;written[(address-8'h10)>>2]<=1;end
                end else if(address==8'h28 && write_data==32'h41524d32) begin
                    if(armed || !idle_allowed || !valid_limits || !healthy) error<=3;
                    else begin armed<=1;tripped<=0;requested<=0;elapsed<=0;lease_age<=0;
                        unhealthy_ms<=0;unhealthy_tick_seen<=0;health_reasons<=0;trip_reasons<=0;end
                end else if(address==8'h2c) begin
                    if(!authorized || write_data>limits[0]) error<=3;
                    else begin requested<=write_data[15:0];lease_age<=0;end
                end else error<=1;
            end
            // Last assignment wins: a command cannot revive a timed out/tripped trial.
            if(armed && (!idle_allowed || health_confirmed || duration_expired || lease_expired)) begin
                armed<=0;tripped<=1;requested<=0;written<=0;
                trip_reasons<=causes | (health_confirmed ? health_reasons:8'd0);
            end
        end
    end
endmodule
