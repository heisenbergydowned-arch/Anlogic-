`timescale 1ns/1ps
module tb_edge_icm;
    reg clk=0;always #5 clk=~clk;reg rst_n=0;
    wire sclk,mosi,miso,csa,csb,va,vb,done,ea,eb;wire [15:0] sa,sb;
    sns_sync #(.POWERUP_MS(1),.RESET_MS(1),.POSTINIT_MS(1),.SAMPLE_HZ(8000)) dut(
        .clk(clk),.rst_n(rst_n),.spi_sclk(sclk),.spi_mosi(mosi),.spi_miso(miso),.cs_icm_a_n(csa),.cs_icm_b_n(csb),
        .vld_icm_a(va),.vld_icm_b(vb),.init_done(done),.err_icm_a(ea),.err_icm_b(eb),.seq_a(sa),.seq_b(sb));
    icm20602_model #(.ODR_HZ(4000)) a(.sclk(sclk),.mosi(mosi),.miso(miso),.cs_n(csa),.halt(1'b0));
    icm20602_model #(.ODR_HZ(4000),.IGNORE_WRITE_ADDR(8'h70)) b(.sclk(sclk),.mosi(mosi),.miso(miso),.cs_n(csb),.halt(1'b0));
    initial begin
        repeat(8)@(negedge clk);rst_n=1;
        wait(done);#2000000;
        if(a.regs[8'h6c]!=7 || a.regs[8'h70]!=8'h40)$fatal(1,"Wrong accel power or I2C interface register");
        if(ea || !eb || sa<3 || sb!=0)$fatal(1,"Readback verification didn't isolate bad ICM: %d %d %d %d",ea,eb,sa,sb);
        $display("tb_edge_icm ALL PASS power/interface/readback fault isolation");$finish;
    end
    initial begin #15000000;$fatal(1,"TIMEOUT ICM init/readback");end
endmodule
