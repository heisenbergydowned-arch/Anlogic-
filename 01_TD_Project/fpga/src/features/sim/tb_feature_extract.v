`timescale 1ns/1ps
module tb_feature_extract;
    localparam CASES=12;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,frame_start=0,sample_valid=0,cfg_we=0,out_ready=0;
    reg [31:0] frame_id=0;
    reg signed [31:0] current_q16=0,temp_q16=0,pressure_q16=0,rpm_q16=0;
    reg [15:0] input_quality=0;
    reg signed [15:0] sample_data=0;
    reg [3:0] cfg_index=0;reg [9:0] cfg_edge=0;
    wire frame_ready,sample_ready,busy,out_valid,out_last,frame_done;
    wire [5:0] out_index;wire signed [31:0] out_q16;
    wire [31:0] out_fp32,out_frame_id;wire [15:0] out_quality;
    feature_extract dut(.*);
    reg [15:0] raw[0:CASES*6144-1];
    reg [31:0] process[0:CASES*4-1];
    reg [9:0] config_edges[0:CASES*9-1];
    reg [15:0] input_flags[0:CASES-1];
    reg [1023:0] raw_path,process_path,edges_path,flags_path,output_path;
    integer fd,c,a,n,j,cycle=0,outputs=0,dones=0;
    reg stalled=0;reg [31:0] held_q,held_fp,held_id;reg [15:0] held_quality;
    reg [5:0] held_index;reg held_last;
    always @(negedge clk) out_ready=(cycle%9)!=0 && (cycle%9)!=1 && (cycle%9)!=2;
    always @(posedge clk) begin
        cycle=cycle+1;
        if (cycle>8000000) $fatal(1,"Feature timeout");
        if (rst_n) begin
            if (stalled && (!out_valid || out_q16!==held_q || out_fp32!==held_fp ||
                out_frame_id!==held_id || out_index!==held_index || out_quality!==held_quality || out_last!==held_last))
                $fatal(1,"Unstable output during backpressure");
            stalled=out_valid && !out_ready;
            held_q=out_q16;held_fp=out_fp32;held_id=out_frame_id;held_index=out_index;
            held_quality=out_quality;held_last=out_last;
            if (out_valid && out_ready) begin
                if (out_index!==outputs%39 || out_frame_id!==outputs/39)
                    $fatal(1,"Feature ordering/frame ID mismatch");
                if (out_last!==(out_index==38)) $fatal(1,"Incorrect last flag");
                $fdisplay(fd,"%0d %0d %0d %08h %04h %0d",out_frame_id,out_index,out_q16,out_fp32,out_quality,cycle);
                outputs=outputs+1;
            end
            if (frame_done) dones=dones+1;
        end else stalled=0;
    end
    task feed;
        input signed [15:0] value;
        begin
            while (!sample_ready) @(negedge clk);
            sample_data=value;sample_valid=1;
            @(negedge clk);sample_valid=0;
        end
    endtask
    initial begin
        if (!$value$plusargs("RAW=%s",raw_path)) $fatal(1,"Missing RAW");
        if (!$value$plusargs("PROCESS=%s",process_path)) $fatal(1,"Missing PROCESS");
        if (!$value$plusargs("EDGES=%s",edges_path)) $fatal(1,"Missing EDGES");
        if (!$value$plusargs("FLAGS=%s",flags_path)) $fatal(1,"Missing FLAGS");
        if (!$value$plusargs("OUT=%s",output_path)) $fatal(1,"Missing OUT");
        $readmemh(raw_path,raw);$readmemh(process_path,process);$readmemh(edges_path,config_edges);$readmemh(flags_path,input_flags);
        fd=$fopen(output_path,"w");if (!fd) $fatal(1,"Output open failed");
        repeat(4) @(negedge clk);rst_n=1;@(negedge clk);
        // Abort a partial frame, then verify fresh frames cannot contain old samples.
        frame_start=1;@(negedge clk);frame_start=0;
        for (n=0;n<25;n=n+1) feed(16'sd1234);
        rst_n=0;repeat(3) @(negedge clk);rst_n=1;@(negedge clk);
        if (!frame_ready || out_valid) $fatal(1,"Reset did not abort partial frame");
        // Reset while each newly shared spectral operation is busy, then
        // run the full independent-reference frames. No stale result may leak.
        for (j=0;j<2;j=j+1) begin
            frame_start=1;@(negedge clk);frame_start=0;
            for(n=0;n<1024;n=n+1) feed(raw[n]);
            if(j==0)wait(dut.state==dut.FREQ_RE_WAIT);
            else wait(dut.state==dut.FREQ_IM_WAIT);
            repeat(5)@(negedge clk);
            if(!dut.squarer.busy)$fatal(1,"Spectral reset did not exercise busy squarer");
            rst_n=0;repeat(3)@(negedge clk);rst_n=1;@(negedge clk);
            if(!frame_ready || out_valid || dut.squarer.busy)$fatal(1,"Spectral reset failed to abort");
        end
        for (c=0;c<CASES;c=c+1) begin
            while (!frame_ready) @(negedge clk);
            for (j=0;j<9;j=j+1) begin
                cfg_we=1;cfg_index=j;cfg_edge=config_edges[c*9+j];@(negedge clk);
            end
            cfg_we=0;frame_id=c;input_quality=input_flags[c];
            current_q16=process[c*4];temp_q16=process[c*4+1];
            pressure_q16=process[c*4+2];rpm_q16=process[c*4+3];
            frame_start=1;@(negedge clk);frame_start=0;
            for (a=0;a<6;a=a+1) for (n=0;n<1024;n=n+1) begin
                if (n%13==0) @(negedge clk);
                feed(raw[c*6144+a*1024+n]);
            end
            while (!frame_ready) @(negedge clk);
            @(negedge clk);
        end
        if (outputs!=CASES*39 || dones!=CASES) $fatal(1,"Missing/duplicate outputs");
        $fclose(fd);$display("PASS feature protocol: %0d frames, %0d features, %0d cycles",CASES,outputs,cycle);$finish;
    end
endmodule
