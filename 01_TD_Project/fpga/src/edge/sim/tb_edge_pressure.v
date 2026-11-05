`timescale 1ns/1ps
module tb_edge_pressure;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0;
    reg [63:0] now_cycles=0;
    wire [31:0] now_ms=now_cycles/16;
    always @(posedge clk)if(!rst_n)now_cycles<=0;else now_cycles<=now_cycles+1;
    reg sample_new=0,adc_new=0,pressure_new=0,pressure_bad=0,adc_bad=0,feature_done=0;
    reg [15:0] sequence_id=0;
    reg signed [15:0] current_raw=100,pressure_raw=6000;
    wire frame_start,frame_abort,window_busy;
    wire [15:0] window_quality,mean_quality;
    wire [31:0] adc_count,pressure_count,pressure_age_ms;
    wire signed [47:0] current_sum,pressure_sum;
    wire mean_done;
    wire signed [31:0] current_mean,pressure_mean;
    edge_window #(.CLK_HZ(16000),.PRESSURE_INDEPENDENT(1)) window(
        .clk(clk),.rst_n(rst_n),.now_cycles(now_cycles),.now_ms(now_ms),
        .a_new(sample_new),.b_new(sample_new),.ax(16'sd1),.ay(16'sd2),.az(16'sd3),
        .bx(16'sd4),.by(16'sd5),.bz(16'sd6),.a_seq(sequence_id),.b_seq(sequence_id),
        .a_bad(1'b0),.b_bad(1'b0),.adc_new(adc_new),.adc_bad(adc_bad),
        .current_raw(current_raw),.pressure_raw(pressure_raw),.pressure_new(pressure_new),.pressure_bad(pressure_bad),
        .temp_new(1'b1),.temp_bad(1'b0),.temp_raw(16'sd480),.fg_new(sample_new),.fg_bad(1'b0),.fg_period(32'd80),
        .enable(1'b1),.control_mode(4'd3),.feature_ready(1'b1),.feature_done(feature_done),.sample_ready(1'b0),
        .frame_start(frame_start),.frame_abort(frame_abort),.busy(window_busy),.quality(window_quality),
        .adc_count(adc_count),.pressure_count(pressure_count),.pressure_age_ms(pressure_age_ms),
        .current_sum(current_sum),.pressure_sum(pressure_sum));
    edge_window_mean #(.PRESSURE_INDEPENDENT(1)) averages(
        .clk(clk),.rst_n(rst_n),.start(frame_start),.current_sum(current_sum),.pressure_sum(pressure_sum),
        .adc_count(adc_count),.pressure_count(pressure_count),.period_sum(64'd80),.fg_count(32'd1),
        .done(mean_done),.current_mean(current_mean),.pressure_mean(pressure_mean),.quality(mean_quality));

    task reset_case;
        begin
            rst_n=0;sample_new=0;adc_new=0;pressure_new=0;pressure_bad=0;adc_bad=0;feature_done=0;
            current_raw=100;pressure_raw=6000;
            repeat(8)@(negedge clk);
            rst_n=1;
        end
    endtask
    task push_sample;
        input integer sample_id;
        input integer pressure_enable;
        input integer pressure_failure;
        input integer current_failure;
        begin
            @(negedge clk);
            sequence_id=sample_id;sample_new=1;adc_new=1;
            pressure_new=pressure_enable && sample_id%40==0;
            pressure_bad=pressure_failure;adc_bad=current_failure;
            @(negedge clk);
            sample_new=0;adc_new=0;pressure_new=0;pressure_bad=0;adc_bad=0;
            repeat(2)@(negedge clk);
        end
    endtask
    task await_mean;
        integer waited;
        begin
            waited=0;
            while(!mean_done && waited<500)begin @(negedge clk);waited=waited+1;end
            if(!mean_done)$fatal(1,"mean timeout");
            if(frame_abort)$fatal(1,"unexpected frame abort");
        end
    endtask
    integer sample_id;
    initial begin
        reset_case;
        for(sample_id=0;sample_id<1024;sample_id=sample_id+1)push_sample(sample_id,1,0,0);
        await_mean;
        if(adc_count!=1023 || pressure_count!=25)$fatal(1,"independent counts ADC=%0d pressure=%0d",adc_count,pressure_count);
        if(current_mean!=32'sd6553600 || pressure_mean!=32'sd393216000)$fatal(1,"independent means %d %d",current_mean,pressure_mean);
        if(window_quality[8] || window_quality[10] || mean_quality)$fatal(1,"nominal pressure quality %h %h",window_quality,mean_quality);
        feature_done=1;@(negedge clk);feature_done=0;
        pressure_raw=-3000;
        for(sample_id=1024;sample_id<1536;sample_id=sample_id+1)push_sample(sample_id,1,0,0);
        await_mean;
        if(pressure_count!=26 || pressure_mean!=32'sd98304000)$fatal(1,"overlap sum/count wrong %0d %d",pressure_count,pressure_mean);

        reset_case;pressure_raw=0;
        for(sample_id=0;sample_id<1024;sample_id=sample_id+1)push_sample(sample_id,1,0,0);
        await_mean;
        if(window_quality[10] || mean_quality[10] || pressure_mean!=0)$fatal(1,"real zero pressure marked invalid");

        reset_case;
        for(sample_id=0;sample_id<1024;sample_id=sample_id+1)push_sample(sample_id,0,0,0);
        await_mean;
        if(!window_quality[10] || !mean_quality[10] || window_quality[8] || pressure_count!=0)$fatal(1,"missing pressure taints current or looks valid");

        reset_case;
        for(sample_id=0;sample_id<1024;sample_id=sample_id+1)push_sample(sample_id,1,sample_id==1023,0);
        await_mean;
        if(!window_quality[10] || window_quality[8])$fatal(1,"boundary pressure fault lost/coupled");

        reset_case;
        for(sample_id=0;sample_id<1024;sample_id=sample_id+1)push_sample(sample_id,1,0,sample_id==1023);
        await_mean;
        if(!window_quality[8] || window_quality[10])$fatal(1,"current fault falsely invalidates digital pressure");

        reset_case;
        for(sample_id=0;sample_id<1024;sample_id=sample_id+1)push_sample(sample_id,sample_id<500,0,0);
        await_mean;
        if(!window_quality[10] || window_quality[8] || pressure_age_ms<100)$fatal(1,"old pressure held as fresh %0d",pressure_age_ms);
        $display("tb_edge_pressure ALL PASS independent counts, means, overlap, valid zero, faults and stale data");
        $finish;
    end
    initial begin #1000000;$fatal(1,"TIMEOUT independent pressure windows");end
endmodule
