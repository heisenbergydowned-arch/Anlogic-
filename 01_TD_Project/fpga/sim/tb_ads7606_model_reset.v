`timescale 1ns/1ps
module tb_ads7606_model_reset;
    reg reset = 0, convst = 0, connected = 1;
    wire busy, douta, frstdata;
    integer observed_busy = 0;
    always @(posedge busy) observed_busy = observed_busy + 1;
    ads7606_model model (
        .reset(reset), .convst(convst), .busy(busy), .sclk(1'b0), .cs_n(1'b1),
        .douta(douta), .frstdata(frstdata), .ch1_code(16'h1234),
        .ch2_code(16'h1234), .ch3_code(16'h1234), .ch4_code(16'h1234),
        .ch5_code(16'h1234), .ch6_code(16'h1234), .ch7_code(16'h1234),
        .ch8_code(16'h1234), .en(connected), .frst_mode(2'd0));
    task convert;
        begin
            convst = 1;
            #200 convst = 0;
            #5000;
        end
    endtask
    initial begin
        #100;
        convert;
        if (observed_busy != 0) $fatal(1, "Uninitialized ADC accepted conversion");
        reset = 1;
        #40 reset = 0;
        #100;
        convert;
        if (observed_busy != 0) $fatal(1, "Short RESET accepted");
        reset = 1;
        #100 reset = 0;
        #100;
        convst = 1;
        #10 reset = 1;
        #100 reset = 0;
        #5000;
        convst = 0;
        if (busy || observed_busy != 0 || model.result !== 0)
            $fatal(1, "Delayed BUSY/completion survived RESET");
        #100;
        convst = 1;
        #100 reset = 1;
        #100 reset = 0;
        convst = 0;
        #5000;
        if (busy || model.result !== 0) $fatal(1, "In-flight conversion survived RESET");
        convert;
        if (model.result !== {8{16'h1234}}) $fatal(1, "Conversion did not recover");
        reset = 1;
        #100 reset = 0;
        #100 convst = 1;
        #10 connected = 0;
        #5000;
        if (busy || model.result !== 0) $fatal(1, "Disconnected conversion completed");
        $display("tb_ads7606_model_reset: ALL PASS");
        $finish;
    end
    initial begin
        #100_000;
        $fatal(2, "tb_ads7606_model_reset TIMEOUT");
    end
endmodule
