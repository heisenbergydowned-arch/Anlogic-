`timescale 1ns/1ps
module tb_sns_timeout;
    parameter SAMPLE_TIMEOUT_MS=10; // also run with -Ptb_sns_timeout.SAMPLE_TIMEOUT_MS=300
    reg clk=0; always #50 clk=~clk; // 10 MHz
    reg rst_n=0;
    wire sclk,mosi,cs_a,cs_b; tri miso;
    wire va,vb,done,ea,eb; wire [7:0] wda,wdb;
    sns_sync #(.CLK_FREQ(10000000),.SAMPLE_HZ(2000),.SPI_DIV(2),
        .POWERUP_MS(1),.RESET_MS(1),.POSTINIT_MS(1),.RETRY_MS(1000),
        .SAMPLE_TIMEOUT_MS(SAMPLE_TIMEOUT_MS)) dut(
        .clk(clk),.rst_n(rst_n),.spi_sclk(sclk),.spi_mosi(mosi),.spi_miso(miso),
        .cs_icm_a_n(cs_a),.cs_icm_b_n(cs_b),.vld_icm_a(va),.vld_icm_b(vb),
        .init_done(done),.err_icm_a(ea),.err_icm_b(eb),.wd_a_cnt(wda),.wd_b_cnt(wdb));
    icm20602_model #(.DATA_BASE(8'h21),.ODR_HZ(990)) ma(.sclk(sclk),.mosi(mosi),.miso(miso),.cs_n(cs_a));
    icm20602_model #(.DATA_BASE(8'h51),.ODR_HZ(995)) mb(.sclk(sclk),.mosi(mosi),.miso(miso),.cs_n(cs_b));
    integer na=0,nb=0,ba,bb; reg [15:0] frozen_a,frozen_b;
    real ta,tb,elapsed;
    always @(posedge clk) if(rst_n) begin
        if(va)begin na=na+1;ta=$realtime;end
        if(vb)begin nb=nb+1;tb=$realtime;end
    end
    initial begin
        repeat(10)@(negedge clk);rst_n=1;
        wait(done && na>=6 && nb>=6); @(negedge clk);
        #20000000;
        if(ea!==0 || eb!==0)$fatal(1,"Healthy DRDY gaps false alarm");
        frozen_a=ma.sample_id; force ma.sample_id=frozen_a; force ma.drdy_r=0;
        ba=na;bb=nb;
        wait(ea===1); elapsed=($realtime-ta)/1e6; @(negedge clk);
        // 门限 + 毫秒节拍与 vld 到达的相位差（≤1ms）+ 沿粒度
        if(elapsed<SAMPLE_TIMEOUT_MS-0.01 || elapsed>SAMPLE_TIMEOUT_MS+1.05 || wda!==1 || eb!==0 || nb-bb<8)
            $fatal(1,"A timeout latency or independence failed: %fms",elapsed);
        $display("ICM A timeout: last-valid age=%0.5fms healthy_B=%0d wd=%0d",elapsed,nb-bb,wda);
        ba=na; #4000000;
        if(na!=ba || wda!==1 || eb!==0)$fatal(1,"A fault emits samples or retriggers");
        release ma.sample_id; release ma.drdy_r;
        // Exercise the existing retry path immediately, including a deliberate
        // 25ms reinitialization pause longer than the 10ms sample timeout.
        force dut.retry_tmr=dut.T_RETRY; force dut.wait_cnt=0;
        wait(dut.st==dut.ST_WHO_ISS1); release dut.retry_tmr; release dut.wait_cnt;
        wait(dut.st==dut.ST_INIT_ISS1);
        wait(dut.st==dut.ST_WAIT);
        force dut.wait_cnt=250000;
        #25000000;
        if(eb!==0)$fatal(1,"Healthy B timed out during scheduled reinitialization");
        release dut.wait_cnt;
        wait(na>ba+5); @(negedge clk);
        if(ea!==0 || eb!==0)$fatal(1,"A recovery failed");
        frozen_b=mb.sample_id; force mb.sample_id=frozen_b; force mb.drdy_r=0;
        ba=na;bb=nb;
        wait(eb===1); elapsed=($realtime-tb)/1e6; @(negedge clk);
        if(elapsed<SAMPLE_TIMEOUT_MS-0.01 || elapsed>SAMPLE_TIMEOUT_MS+1.05 || wdb!==1 || ea!==0 || na-ba<8)
            $fatal(1,"B timeout latency or independence failed: %fms",elapsed);
        $display("ICM B timeout: last-valid age=%0.5fms healthy_A=%0d wd=%0d",elapsed,na-ba,wdb);
        bb=nb; #4000000;
        if(nb!=bb || wdb!==1 || ea!==0)$fatal(1,"B fault emits samples or retriggers");
        $display("tb_sns_timeout: ALL PASS"); $finish;
    end
    initial begin #((2*SAMPLE_TIMEOUT_MS+180)*1000000); $fatal(1,"ICM timeout test TIMEOUT"); end
endmodule
