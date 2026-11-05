`timescale 1ns/1ps
module tb_edge_features #(parameter DIGITAL_PRESSURE=0);
    // 4MHz logical time allows the serial arithmetic budget; physical target stays 100MHz.
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0;reg [31:0] now_ms=0;reg [11:0] ms_div=0;
    always @(posedge clk)if(ms_div==3999)begin ms_div<=0;now_ms<=now_ms+1;end else ms_div<=ms_div+1;
    wire sample_new,adc_new,temp_new,fg_new;wire signed [15:0] ax,ay,az,bx,by,bz,ci,pr,tr;
    wire [15:0] seq;wire [31:0] period;
    reg [15:0] pressure_timer=0;
    reg digital_pressure_new=0;
    always @(posedge clk)begin
        if(!rst_n)begin pressure_timer<=0;digital_pressure_new<=0;end
        else begin
            digital_pressure_new<=pressure_timer==39999;
            if(pressure_timer==39999)pressure_timer<=0;else pressure_timer<=pressure_timer+1;
        end
    end
    edge_test_source #(.CLK_HZ(4000000)) source(.clk(clk),.rst_n(rst_n),.sample_new(sample_new),.adc_new(adc_new),.temp_new(temp_new),.fg_new(fg_new),
        .ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),.sample_seq(seq),.current_raw(ci),.pressure_raw(pr),.temp_raw(tr),.fg_period(period));
    reg req=0,we=0;reg [15:0] addr=0;reg [31:0] wd=0;wire response;wire [31:0] rd;wire [7:0] error;wire available,busy;
    edge_features #(.CLK_HZ(4000000),.TEST_MODE(1),.PRESSURE_INDEPENDENT(DIGITAL_PRESSURE)) dut(.clk(clk),.rst_n(rst_n),.now_ms(now_ms),
        .a_new(sample_new),.b_new(sample_new),.ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),.a_seq(seq),.b_seq(seq),.a_bad(1'b0),.b_bad(1'b0),
        .adc_new(adc_new),.adc_bad(1'b0),.current_raw(ci),.pressure_raw(DIGITAL_PRESSURE ? 16'sd6000:pr),
        .pressure_new(digital_pressure_new),.pressure_bad(1'b0),.temp_new(temp_new),.temp_bad(1'b0),.temp_raw(tr),
        .fg_new(fg_new),.fg_bad(1'b0),.fg_period(period),.control_mode(4'd3),.local_permit(1'b1),.initial_config_permit(1'b0),
        .req(req),.write_en(we),.address(addr),.wdata(wd),.response(response),.rdata(rd),.error(error),.frame_available(available),.busy(busy));
    // Production uses serial header storage: all 32 words must remain equal
    // to the index-0 snapshot while indices 1..38 are emitted.
    reg [1023:0] held_header;
    always @(posedge clk)if(rst_n && dut.out_valid)begin
        if(dut.out_index==0)held_header<=dut.header;
        else if(dut.header!==held_header)$fatal(1,"Serial producer changed header at feature %0d",dut.out_index);
    end
    integer fd,i,frames=0;reg [31:0] value,frameid;reg [1023:0] path;
    task access;input write;input [15:0] address;input [31:0] data;begin
        @(negedge clk);req=1;we=write;addr=address;wd=data;
        @(negedge clk);req=0;
        if(!response || error!=0)$fatal(1,"CSR error addr=%h error=%d",address,error);
        value=rd;
    end endtask
    initial begin
        if(!$value$plusargs("OUT=%s",path))$fatal(1,"Missing OUT");fd=$fopen(path,"w");
        repeat(8)@(negedge clk);rst_n=1;
        while(frames<3)begin
            wait(available);
            access(0,16'h1010,0);frameid=value;
            for(i=0;i<32;i=i+1)begin access(0,16'h1100+i*4,0);$fwrite(fd,"%08x ",value);end
            for(i=0;i<39;i=i+1)begin access(0,16'h1200+i*4,0);$fwrite(fd,"%08x ",value);end
            $fwrite(fd,"\n");access(1,16'h1010,frameid);access(1,16'h1010,frameid); // identical ACK can't pop next
            frames=frames+1;
        end
        $fclose(fd);$display("tb_edge_features ALL PASS %0d complete frames",frames);$finish;
    end
    initial begin #30000000;$fatal(1,"TIMEOUT feature chain");end
endmodule
