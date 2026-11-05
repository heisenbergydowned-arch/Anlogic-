`timescale 1ns/1ps
module tb_environment;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0;
    reg [31:0] now_ms=0;
    reg aht_new=0,bmp_new=0,aht_present=0,bmp_present=0,aht_error=0,bmp_error=0;
    reg [19:0] aht_temperature=393216,aht_humidity=524288,bmp_temperature=519888,bmp_pressure=415148;
    reg [191:0] bmp_calibration=192'h1770c6f83c8cfff9008c0b270bd0d6438e7dfc1867436b70;
    wire aht_valid,bmp_valid,auxiliary_bad,aht_stale,bmp_stale,response;
    reg req=0,write_en=0;reg [15:0] address=0;
    wire [31:0] read_data;wire [7:0] error;
    reg [31:0] captured[0:19];integer word_index,fd;
    reg [2047:0] output_path;
    edge_environment dut(.*);
    task read_word(input [15:0] location,input [7:0] expected_error);
        begin
            @(negedge clk); address=location;req=1;
            @(posedge clk);#1;
            if(!response || error!=expected_error)$fatal(1,"CSR response/error %h %h",location,error);
            @(negedge clk); req=0;
            @(posedge clk);#1;
        end
    endtask
    task fresh;
        begin
            @(negedge clk);aht_new=1;bmp_new=1;
            @(negedge clk);aht_new=0;bmp_new=0;
            #1;
        end
    endtask
    initial begin
        repeat(3)@(negedge clk);rst_n=1;
        #1;if(!auxiliary_bad || aht_valid || bmp_valid)$fatal(1,"Unseen sensors valid");
        aht_present=1;bmp_present=1;now_ms=1000;fresh();
        if(auxiliary_bad || !aht_valid || !bmp_valid)$fatal(1,"Good sensors rejected");
        read_word(16'h3000,0);captured[0]=read_data;
        for(word_index=1;word_index<20;word_index=word_index+1)begin
            read_word(16'h3000+word_index*4,0);captured[word_index]=read_data;
        end
        if(captured[0]!=32'h454e5631 || captured[4]!=32'h27 || captured[19]!=2)$fatal(1,"Snapshot ABI/flags");
        if(captured[8]!=393216 || captured[9]!=519888 || captured[10]!=415148)$fatal(1,"Snapshot raw");
        if($value$plusargs("OUT=%s",output_path))begin
            fd=$fopen(output_path,"w");if(!fd)$fatal(1,"Output open");
            for(word_index=0;word_index<20;word_index=word_index+1)$fdisplay(fd,"%08x",captured[word_index]);
            $fclose(fd);
        end
        now_ms=3500;#1;if(auxiliary_bad)$fatal(1,"Inclusive age boundary");
        now_ms=3501;@(negedge clk);#1;if(!auxiliary_bad || !aht_stale || !bmp_stale)$fatal(1,"Stale not detected");
        read_word(16'h3010,0);if(read_data!=32'h27)$fatal(1,"Snapshot mutated without capture");
        now_ms=1001;#1;if(!aht_stale)$fatal(1,"Expired sample resurrected after timer wrap");
        fresh();if(auxiliary_bad)$fatal(1,"Recovery failed");
        aht_error=1;#1;if(aht_valid || !auxiliary_bad || !bmp_valid)$fatal(1,"AHT failure isolation");
        aht_error=0;bmp_error=1;#1;if(bmp_valid || !auxiliary_bad || !aht_valid)$fatal(1,"BMP failure isolation");
        bmp_error=0;bmp_calibration[63:48]=0;#1;if(bmp_valid)$fatal(1,"P1 zero accepted");
        bmp_calibration[63:48]=36477;bmp_temperature=20'h80000;#1;if(bmp_valid)$fatal(1,"Skipped conversion accepted");
        bmp_temperature=519888;aht_temperature=0;#1;if(aht_valid)$fatal(1,"Impossible AHT temperature accepted");
        aht_temperature=393216;
        now_ms=32'hfffffff0;fresh();now_ms=16;#1;if(auxiliary_bad)$fatal(1,"Valid sample failed across wrap");
        read_word(16'h3001,2);read_word(16'h3050,2);
        write_en=1;read_word(16'h3000,2);write_en=0;
        @(negedge clk);req=1;address=16'h3000;@(posedge clk);#1;if(!response)$fatal(1,"Capture response");
        repeat(3)begin @(posedge clk);#1;if(response)$fatal(1,"Repeated response on held request");end
        $display("tb_environment ALL PASS freshness/expiry/wrap/faults/atomic CSR/readonly/range");$finish;
    end
    initial begin #100000;$fatal(1,"TIMEOUT environment");end
endmodule
