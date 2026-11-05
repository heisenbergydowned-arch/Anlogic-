`timescale 1ns/1ps
module tb_control_uart;
    reg clk=0,rst_n=0,rx=1;always #5 clk=~clk;
    wire ctrl_tx,ctrl_active,holdoff,dbg_tx,dbg_busy;
    wire tx=ctrl_active ? ctrl_tx:dbg_tx;
    wire req,wr;wire [15:0] addr;wire [31:0] wd;
    reg response=0;reg [31:0] rd=0;reg [7:0] error=0;
    wire [31:0] bad_frames,busy_drops;
    integer writes=0,reads=0,checks=0,reply_count=0,debug_count=0;
    reg [31:0] last_write=0;
    cooling_uart #(.CLK_FREQ(1_000_000),.BAUD(100000)) dut(.clk(clk),.rst_n(rst_n),.rx(rx),.dbg_busy(dbg_busy),
        .dbg_holdoff(holdoff),.tx(ctrl_tx),.tx_active(ctrl_active),.req(req),.write_en(wr),.address(addr),.write_data(wd),
        .response(response),.read_data(rd),.error(error),.bad_frames(bad_frames),.busy_drops(busy_drops));
    dbg_uart #(.CLK_FREQ(1_000_000),.BAUD(100000),.FRAME_MS(2),.CAL_DIV(2),.ARBITRATION(1)) debug_uart(
        .clk(clk),.rst_n(rst_n),.holdoff(holdoff),.frame_busy(dbg_busy),.tx(dbg_tx),
        .d_status(16'h1111),.d_seq_a(16'd1),.d_seq_b(16'd2),.d_tick(16'd3),
        .d_vld_a(16'd0),.d_vld_b(16'd0),.d_drdy0_a(16'd0),.d_drdy0_b(16'd0),.d_wd_a(8'd0),.d_wd_b(8'd0),
        .d_dup_a(16'd0),.d_dup_b(16'd0),.d_bmp_cal(192'd0),.d_bmp_cal_vld(1'b1),
        .d_a_ax(16'd0),.d_a_ay(16'd0),.d_a_az(16'd0),.d_b_ax(16'd0),.d_b_ay(16'd0),.d_b_az(16'd0),
        .d_adc1(16'd0),.d_adc2(16'd0),.d_adc3(16'd0),.d_adc4(16'd0),.d_adc5(16'd0),.d_adc6(16'd0),.d_adc7(16'd0),.d_adc8(16'd0),
        .d_fg_period(32'd0),.d_fg_pcount(32'd0),.d_inlet_aht_q4(16'd0),.d_core_temp_q4(16'd0),
        .d_aht_hum(20'd0),.d_aht_temp(20'd0),.d_bmp_t(20'd0),.d_bmp_p(20'd0));
    always @(posedge clk)begin
        response<=rst_n && req;
        if(rst_n && req)begin
            error<=addr[1:0]!=0 ? 1:0;rd<=wr ? wd:32'h46434231;
            if(wr)begin writes<=writes+1;last_write<=wd;end else reads<=reads+1;
        end
    end
    function [15:0] crc;
        input [15:0] old;input [7:0] b;reg [15:0] c;integer k;
        begin c=old^{b,8'd0};for(k=0;k<8;k=k+1)c=c[15] ? (c<<1)^16'h1021:c<<1;crc=c;end
    endfunction
    task check;input ok;input [511:0] name;begin checks=checks+1;if(ok!==1'b1)$fatal(1,"FAIL %0s",name);end endtask
    task send_byte;
        input [7:0] b;input stop_good;integer k;
        begin @(negedge clk);rx=0;repeat(10)@(negedge clk);
            for(k=0;k<8;k=k+1)begin rx=b[k];repeat(10)@(negedge clk);end
            rx=stop_good;repeat(10)@(negedge clk);rx=1;
        end
    endtask
    reg [111:0] packet;
    task send_packet;
        input [7:0] version,op;input [15:0] seq_arg,location;input [31:0] value;input bad_crc;
        reg [15:0] c;integer k;
        begin
            packet={16'd0,value,location,seq_arg,op,version,8'h51,8'hc3};c=16'hffff;
            for(k=0;k<12;k=k+1)c=crc(c,packet[k*8 +:8]);
            packet[111:96]=bad_crc ? c^16'h100:c;
            for(k=0;k<14;k=k+1)send_byte(packet[k*8 +:8],1);
        end
    endtask
    task get_byte;
        output [7:0] b;integer k;
        begin @(negedge tx);#150;for(k=0;k<8;k=k+1)begin b[k]=tx;#100;end
            check(tx==1,"UART stop bit and frame arbitration");
        end
    endtask
    reg [7:0] received[0:76];
    reg [15:0] reply_sequence,reply_address;
    reg [31:0] reply_data;
    reg [7:0] reply_error;
    integer n,j;reg [7:0] xor_sum;reg [15:0] crc_sum;
    initial begin
        wait(rst_n);
        forever begin
            get_byte(received[0]);get_byte(received[1]);
            if(received[0]==8'h55 && (received[1]==8'ha5 || received[1]==8'ha6))begin
                n=received[1]==8'ha5 ? 77:27;xor_sum=received[0]^received[1];
                for(j=2;j<n;j=j+1)begin get_byte(received[j]);if(j<n-1)xor_sum=xor_sum^received[j];end
                check(received[n-1]==xor_sum,"Legacy debug frame remains complete");debug_count=debug_count+1;
            end else begin
                check(received[0]==8'hc3 && received[1]==8'h52,"Response frame synchronization");
                for(j=2;j<16;j=j+1)get_byte(received[j]);
                crc_sum=16'hffff;for(j=0;j<14;j=j+1)crc_sum=crc(crc_sum,received[j]);
                check({received[15],received[14]}==crc_sum,"Response CRC");check(received[2]==1 && received[13]==0,"Response ABI");
                reply_error=received[3];reply_sequence={received[5],received[4]};reply_address={received[7],received[6]};
                reply_data={received[11],received[10],received[9],received[8]};reply_count=reply_count+1;
            end
        end
    end
    task wait_reply;input integer count;input [15:0] seq;input [7:0] expected;
        begin wait(reply_count>=count);check(reply_sequence==seq && reply_error==expected,"Request/response association");repeat(8)@(posedge clk);end
    endtask
    reg [31:0] before_bad;
    initial begin
        repeat(5)@(negedge clk);rst_n=1;
        wait(dbg_busy);send_packet(1,0,16'h1234,0,0,0);wait_reply(1,16'h1234,0);
        check(debug_count>=1 && reply_data==32'h46434231,"Response waits for whole debug frame");
        send_packet(1,1,16'h2345,4,32'hdeadbeef,0);wait_reply(2,16'h2345,0);
        check(writes==1 && last_write==32'hdeadbeef,"One valid packet causes exactly one write");
        before_bad=bad_frames;send_packet(1,1,16'h3456,4,32'hbadbad00,1);repeat(200)@(posedge clk);
        check(writes==1 && bad_frames>before_bad,"Bad CRC cannot write registers");
        send_packet(2,1,16'h4567,4,32'hbadbad01,0);wait_reply(3,16'h4567,1);check(writes==1,"Unsupported ABI cannot write");
        send_packet(1,2,16'h5678,4,32'hbadbad02,0);wait_reply(4,16'h5678,1);check(writes==1,"Unsupported operation cannot write");
        before_bad=bad_frames;send_byte(8'hc3,1);send_byte(8'h51,1);repeat(21000)@(posedge clk);
        check(bad_frames>before_bad,"Truncated frame times out");
        send_packet(1,0,16'h6789,5,0,0);wait_reply(5,16'h6789,1);
        wait(dbg_busy);send_packet(1,0,16'h7001,0,0,0);send_packet(1,1,16'h7002,4,32'hbadbad03,0);
        wait_reply(6,16'h7001,0);check(writes==1 && busy_drops>0,"Busy packet is observable and cannot interleave/execute");
        send_packet(1,0,16'h7003,0,0,0);wait_reply(7,16'h7003,0);check(reads==4,"Transport recovers after errors and busy traffic");
        $display("ALL PASS tb_control_uart checks=%0d debug_frames=%0d",checks,debug_count);$finish;
    end
    initial begin #3000000;$fatal(1,"TIMEOUT tb_control_uart");end
endmodule
