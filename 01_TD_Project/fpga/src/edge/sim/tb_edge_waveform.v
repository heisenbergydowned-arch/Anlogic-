`timescale 1ns/1ps
module tb_edge_waveform;
    parameter PRE=3,POST=2,TEST=0;
    localparam DEPTH=PRE+POST;
    localparam [63:0] TIMEOUT=(POST+8)*1000;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,enable=0,stop=0,a_new=0,b_new=0,a_bad=0,b_bad=0;
    reg signed [15:0] ax=0,ay=0,az=0,bx=0,by=0,bz=0;
    reg [15:0] a_seq=0,b_seq=0;
    reg [63:0] now_cycles=0;
    reg [31:0] now_ms=0;
    reg trigger=0,release_req=0;
    reg [31:0] release_id=0;
    reg req=0,write_en=0;reg [15:0] address=0;reg [31:0] wdata=0;
    wire armed,capturing,available,response,release_ack;
    wire [31:0] event_id,dropped,rdata;wire [7:0] error;
    edge_waveform #(.CLK_HZ(4000000),.SAMPLE_HZ(4000),.PRE_SAMPLES(PRE),.POST_SAMPLES(POST),
        .POST_TIMEOUT_CYCLES(TIMEOUT),.TEST_MODE(TEST)) dut(
        .clk(clk),.rst_n(rst_n),.now_cycles(now_cycles),.now_ms(now_ms),.enable(enable),.stop(stop),
        .a_new(a_new),.b_new(b_new),.ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),
        .a_seq(a_seq),.b_seq(b_seq),.a_bad(a_bad),.b_bad(b_bad),.trigger(trigger),
        .trigger_reason(32'h12345678),.trigger_frame_id(32'd42),
        .trigger_frame_start(64'h1122334455667788),.trigger_frame_end(64'h99aabbccddeeff00),
        .release_req(release_req),.release_id(release_id),.release_ack(release_ack),
        .armed(armed),.capturing(capturing),.event_available(available),.event_id(event_id),.dropped_triggers(dropped),
        .req(req),.write_en(write_en),.address(address),.wdata(wdata),.response(response),.rdata(rdata),.error(error));

    // Test oracle stores literal stimuli and explicitly supplied quality flags.
    // It uses a shifting history queue, independent of the DUT ring addresses.
    reg [143:0] ha[0:1023],hb[0:1023],ea[0:1023],eb[0:1023];
    integer nh_a=0,nh_b=0,ne_a=0,ne_b=0,np_a=0,np_b=0,ep_a=0,ep_b=0,mode=0;
    integer checks=0,i,j,w,warm;reg [31:0] value,id_keep,drop_keep,want;
    reg [7:0] got_error;reg [63:0] t,trigger_stamp;
    task remember;
        input sensor;input [143:0] sample;
        integer k;
        begin
            if(mode==0 && PRE>0)begin
                if(!sensor)begin
                    if(nh_a==PRE)begin for(k=1;k<PRE;k=k+1)ha[k-1]=ha[k];nh_a=nh_a-1;end
                    ha[nh_a]=sample;nh_a=nh_a+1;
                end else begin
                    if(nh_b==PRE)begin for(k=1;k<PRE;k=k+1)hb[k-1]=hb[k];nh_b=nh_b-1;end
                    hb[nh_b]=sample;nh_b=nh_b+1;
                end
            end else if(mode==1)begin
                if(!sensor && np_a<POST)begin ea[ne_a]=sample;ne_a=ne_a+1;np_a=np_a+1;end
                if(sensor && np_b<POST)begin eb[ne_b]=sample;ne_b=ne_b+1;np_b=np_b+1;end
            end
        end
    endtask
    task drive;
        input [3:0] mask;input integer n;input [15:0] seq;input [63:0] stamp;
        input [15:0] qa,qb;
        begin
            a_new=mask[0];b_new=mask[1];a_bad=mask[2];b_bad=mask[3];
            ax=n;ay=-n;az=n+100;bx=-n;by=n+200;bz=-n-300;
            a_seq=seq;b_seq=seq;now_cycles=stamp;now_ms=32'd7654;
            if(enable && !stop && a_new && !a_bad)remember(0,{qa,a_seq,stamp,az,ay,ax});
            if(enable && !stop && b_new && !b_bad)remember(1,{qb,b_seq,stamp,bz,by,bx});
        end
    endtask
    task push;
        input [3:0] mask;input integer n;input [15:0] seq;input [63:0] stamp;
        input [15:0] qa,qb;
        begin
            @(negedge clk);drive(mask,n,seq,stamp,qa,qb);
            @(negedge clk);a_new=0;b_new=0;a_bad=0;b_bad=0;
        end
    endtask
    task fire;
        input [3:0] mask;input integer n;input [15:0] seq;input [63:0] stamp;
        integer k;
        begin
            @(negedge clk);
            ep_a=nh_a;ep_b=nh_b;ne_a=nh_a;ne_b=nh_b;np_a=0;np_b=0;
            for(k=0;k<nh_a;k=k+1)ea[k]=ha[k];
            for(k=0;k<nh_b;k=k+1)eb[k]=hb[k];
            mode=1;trigger=1;trigger_stamp=stamp;drive(mask,n,seq,stamp,0,0);
            @(negedge clk);trigger=0;a_new=0;b_new=0;a_bad=0;b_bad=0;
        end
    endtask
    task raw_access;
        input wr;input [15:0] addr;input [31:0] data;
        integer limit;
        begin
            @(negedge clk);req=1;write_en=wr;address=addr;wdata=data;
            @(negedge clk);req=0;limit=0;
            while(!response && limit<12)begin @(negedge clk);limit=limit+1;end
            if(!response)$fatal(1,"Missing CSR response at %h",addr);
            value=rdata;got_error=error;checks=checks+1;
            @(negedge clk);
        end
    endtask
    // Virtual addresses are test notation only; actual bus uses INDEX/DATA.
    task access;
        input wr;input [15:0] addr;
        reg [31:0] selection;reg [15:0] relative;
        begin
            if(addr>=16'h3000)begin
                relative=addr-(addr>=16'h7000 ? 16'h7000:16'h3000);
                selection=(addr>=16'h7000 ? 32'h80000000:0) | ((relative>>5)<<3) | relative[4:2];
                raw_access(1,16'h20c0,selection);
                if(got_error!=0)$fatal(1,"INDEX rejected %h",selection);
                raw_access(wr,16'h20c4+addr[1:0],0);
            end else raw_access(wr,addr,0);
        end
    endtask
    task expect_csr;
        input [15:0] addr;input [31:0] expected;
        begin access(0,addr);if(got_error!=0 || value!==expected)
            $fatal(1,"CSR %h got %h err %d expected %h",addr,value,got_error,expected);end
    endtask
    task wait_ready;
        integer limit;
        begin
            limit=0;
            while(!available && limit<2*DEPTH+20)begin @(negedge clk);limit=limit+1;end
            if(!available)$fatal(1,"Event did not finish");mode=2;
        end
    endtask
    task check_records;
        integer sensor,k,word_index;reg [143:0] record;reg [15:0] addr;
        reg [31:0] expected;
        begin
            expect_csr(16'h2048,ne_a);expect_csr(16'h204c,ne_b);
            expect_csr(16'h2050,ep_a);expect_csr(16'h2054,ep_b);
            expect_csr(16'h2058,np_a);expect_csr(16'h205c,np_b);
            for(sensor=0;sensor<2;sensor=sensor+1)begin
                for(k=0;k<(sensor ? ne_b:ne_a);k=k+1)begin
                    record=sensor ? eb[k]:ea[k];
                    for(word_index=0;word_index<5;word_index=word_index+1)begin
                        case(word_index)
                            0:expected=record[31:0];
                            1:expected={record[127:112],record[47:32]};
                            2:expected=record[79:48];
                            3:expected=record[111:80];
                            4:expected={16'd0,record[143:128]};
                        endcase
                        raw_access(1,16'h20c0,(sensor ? 32'h80000000:0) | (k<<3) | word_index);
                        if(got_error!=0)$fatal(1,"Record INDEX write failed");
                        raw_access(0,16'h20c4,0);
                        if(got_error!=0 || value!==expected)$fatal(1,"Record sensor=%0d sample=%0d word=%0d got=%h expected=%h",
                            sensor,k,word_index,value,expected);
                    end
                end
            end
            if(ne_a>0)begin
                expect_csr(16'h2060,ea[0][79:48]);expect_csr(16'h2064,ea[0][111:80]);
                expect_csr(16'h2068,ea[ne_a-1][79:48]);expect_csr(16'h206c,ea[ne_a-1][111:80]);
                expect_csr(16'h2080,{ea[ne_a-1][127:112],ea[0][127:112]});
            end
            if(ne_b>0)begin
                expect_csr(16'h2070,eb[0][79:48]);expect_csr(16'h2074,eb[0][111:80]);
                expect_csr(16'h2078,eb[ne_b-1][79:48]);expect_csr(16'h207c,eb[ne_b-1][111:80]);
                expect_csr(16'h2084,{eb[ne_b-1][127:112],eb[0][127:112]});
            end
        end
    endtask
    task release_event;
        begin
            @(negedge clk);release_req=1;release_id=event_id;
            @(negedge clk);release_req=0;
            if(!release_ack || available)$fatal(1,"Matching release failed");
            nh_a=0;nh_b=0;mode=0;
        end
    endtask
    task reset_dut;
        begin
            @(negedge clk);rst_n=0;req=0;trigger=0;release_req=0;a_new=0;b_new=0;a_bad=0;b_bad=0;
            stop=0;enable=1;mode=0;nh_a=0;nh_b=0;
            repeat(3)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);
            if(!armed || available || event_id!=0)$fatal(1,"Reset failed");
        end
    endtask

    initial begin
        reset_dut();expect_csr(16'h2000,32'h57415631);expect_csr(16'h2004,32'h00010000);
        expect_csr(16'h2018,PRE);expect_csr(16'h201c,POST);
        expect_csr(16'h20a8,TEST!=0 ? 1:0);expect_csr(16'h2008,TEST!=0 ? 33:1);
        access(0,16'h3000);if(got_error!=5)$fatal(1,"Unowned RAM visible after reset");
        // Several wraps, independent A/B arrival, 16-bit seq and 64-bit time wrap.
        warm=PRE+2*DEPTH+4;t=64'hfffffffffffe0000;
        for(i=0;i<warm;i=i+1)begin
            push(1,i,16'hfffc+i,t+i*1000,0,0);
            push(2,i,16'hfffc+i,t+i*1000+30,0,0);
        end
        fire(1,warm,16'hfffc+warm,t+warm*1000);
        if(POST>0)push(2,warm,16'hfffc+warm,t+warm*1000+30,0,0);
        for(i=1;i<POST;i=i+1)begin
            push(1,warm+i,16'hfffc+warm+i,t+(warm+i)*1000,0,0);
            push(2,warm+i,16'hfffc+warm+i,t+(warm+i)*1000+30,0,0);
        end
        wait_ready();check_records();expect_csr(16'h2020,0);
        expect_csr(16'h2024,32'h12345678);expect_csr(16'h2028,42);expect_csr(16'h202c,7654);
        expect_csr(16'h2030,trigger_stamp[31:0]);expect_csr(16'h2034,trigger_stamp[63:32]);
        expect_csr(16'h2038,32'h55667788);expect_csr(16'h203c,32'h11223344);
        expect_csr(16'h2040,32'hddeeff00);expect_csr(16'h2044,32'h99aabbcc);
        expect_csr(16'h2088,0);expect_csr(16'h208c,0);expect_csr(16'h2090,0);expect_csr(16'h2094,0);
        access(0,16'h3001);if(got_error!=1)$fatal(1,"Unaligned CSR accepted");
        access(1,16'h200c);if(got_error!=1)$fatal(1,"Write accepted by read-only CSR");
        access(0,16'h3014);if(got_error!=1)$fatal(1,"Undefined record word accepted");
        access(0,ne_a==1024 ? 16'h3014:16'h3000+ne_a*32);if(got_error!=1)$fatal(1,"Stale ring tail visible");
        id_keep=event_id;drop_keep=dropped;
        // Long PS stall: inputs and retriggers must never alter frozen samples.
        for(i=0;i<20;i=i+1)begin
            @(negedge clk);trigger=1;drive(3,900+i,i,now_cycles+1000,0,0);
            @(negedge clk);trigger=0;a_new=0;b_new=0;
        end
        if(event_id!=id_keep || dropped!=drop_keep+20)$fatal(1,"Frozen ownership/drop accounting failed");
        check_records();expect_csr(16'h2020,0);
        @(negedge clk);release_req=1;release_id=id_keep+1;
        @(negedge clk);release_req=0;if(release_ack || !available)$fatal(1,"Wrong ID released event");
        @(negedge clk);stop=1;enable=0;repeat(3)@(negedge clk);
        if(!available)$fatal(1,"Stop erased ready event");check_records();release_event();
        if(armed)$fatal(1,"Released stopped recorder rearmed");
        @(negedge clk);stop=0;enable=1;repeat(2)@(negedge clk);
        @(negedge clk);release_req=1;release_id=id_keep;
        @(negedge clk);release_req=0;if(release_ack)$fatal(1,"Repeated release acknowledged without ownership");
        // Empty early trigger and timeout: no zero padding or stale RAM exposure.
        fire(0,0,0,64'd1000000);
        @(negedge clk);now_cycles=trigger_stamp+TIMEOUT;wait_ready();check_records();
        want=(PRE>0 ? 32'h300:0) | (POST>0 ? 32'h2c00:0);
        expect_csr(16'h2020,want);release_event();

        if(PRE>=1 && POST>=2)begin
            // Rejected A, sequence jump, timing gap, rail value; B stops arriving.
            push(3,10,10,64'd2000000,0,0);fire(0,0,0,64'd2000500);
            access(0,16'h3000);if(got_error!=5)$fatal(1,"Partial capture readable");
            push(5,11,11,64'd2001000,0,0); // a_new && a_bad: must not write
            push(1,32767,13,64'd2004000,16'h000f,0);
            @(negedge clk);stop=1;push(3,12,14,64'd2005000,0,0); // stopped samples excluded
            wait_ready();check_records();
            want=32'h4000 | 32'h1000 | 32'h0400 | 32'h0800 | 32'h000f;
            if(PRE>1)want=want | 32'h0300;
            expect_csr(16'h2020,want);expect_csr(16'h2088,1);expect_csr(16'h208c,0);
            expect_csr(16'h2090,1);expect_csr(16'h2094,0);
            release_event();@(negedge clk);stop=0;repeat(2)@(negedge clk);
            // A completes alone; B's missing stream is bounded by timeout.
            fire(0,0,0,64'd3000000);
            for(i=0;i<POST;i=i+1)push(1,20+i,20+i,64'd3001000+i*1000,0,0);
            @(negedge clk);now_cycles=trigger_stamp+TIMEOUT;wait_ready();check_records();
            expect_csr(16'h2020,32'h2b00);release_event();
            // The B quality nibble/counters must stay independent of A.
            push(3,50,50,64'd3500000,0,0);fire(0,0,0,64'd3500500);
            push(10,51,51,64'd3501000,0,0);
            push(2,32768,53,64'd3504000,0,16'h000f);
            @(negedge clk);stop=1;wait_ready();check_records();
            want=32'h9cf0 | (PRE>1 ? 32'h0300:0);
            expect_csr(16'h2020,want);expect_csr(16'h2088,0);expect_csr(16'h208c,1);
            expect_csr(16'h2090,0);expect_csr(16'h2094,1);
            release_event();@(negedge clk);stop=0;repeat(2)@(negedge clk);
            // Disable commits partial record as STOP; reset discards ownership.
            fire(3,30,30,64'd4000000);@(negedge clk);enable=0;wait_ready();check_records();
            expect_csr(16'h2020,32'h1f00);reset_dut();
            fire(0,0,0,64'd5000000);reset_dut();
            access(0,16'h3000);if(got_error!=5)$fatal(1,"Reset capture left stale RAM readable");
        end
        // Stop while armed clears history, so restarting cannot claim stale PRE.
        reset_dut();push(3,1,1,64'd6000000,0,0);
        @(negedge clk);stop=1;repeat(2)@(negedge clk);
        @(negedge clk);stop=0;repeat(2)@(negedge clk);
        fire(0,0,0,64'd6001000);@(negedge clk);now_cycles=trigger_stamp+TIMEOUT;
        wait_ready();expect_csr(16'h2048,0);expect_csr(16'h204c,0);
        reset_dut();
        // Software controls and indexed DATA remain on the same 4 KiB page.
        raw_access(1,16'h20c0,32'h00002000);if(got_error!=2)$fatal(1,"Reserved INDEX bits accepted");
        raw_access(1,16'h20c0,32'h80000004);if(got_error!=0)$fatal(1,"INDEX write failed");
        expect_csr(16'h20c0,32'h80000004);
        raw_access(1,16'h20c4,1);if(got_error!=1)$fatal(1,"DATA write accepted");
        raw_access(0,16'h2ffc,0);if(got_error!=1)$fatal(1,"Undefined page word accepted");
        raw_access(0,16'h1ffc,0);if(got_error!=1)$fatal(1,"Other CSR page accepted");
        raw_access(1,16'h20b4,1);if(got_error!=0 || armed)$fatal(1,"CSR STOP failed");
        repeat(3)@(negedge clk);if(armed)$fatal(1,"CSR STOP did not latch");
        raw_access(1,16'h20bc,1);if(got_error!=5)$fatal(1,"Stopped manual trigger accepted");
        raw_access(1,16'h20b0,2);if(got_error!=2)$fatal(1,"Invalid ARM payload accepted");
        raw_access(1,16'h20b0,1);if(got_error!=0 || !armed)$fatal(1,"CSR ARM failed");
        // Empty manual event, terminated by software STOP if POST is nonzero.
        raw_access(1,16'h20bc,1);if(got_error!=0)$fatal(1,"Manual trigger rejected");
        if(POST>0)begin
            raw_access(1,16'h20b0,1);if(got_error!=5)$fatal(1,"ARM during capture accepted");
            raw_access(1,16'h20b8,event_id);if(got_error!=4)$fatal(1,"Release during capture accepted");
            raw_access(1,16'h20b4,1);if(got_error!=0)$fatal(1,"CSR STOP capture failed");
        end
        wait_ready();expect_csr(16'h20a4,2);expect_csr(16'h2024,32'h80000000);
        expect_csr(16'h2048,0);expect_csr(16'h204c,0);
        want=(PRE>0 ? 32'h0300:0) | (POST>0 ? 32'h1c00:0);expect_csr(16'h2020,want);
        raw_access(1,16'h20b8,event_id+1);if(got_error!=4 || !available)$fatal(1,"Wrong CSR release ID accepted");
        raw_access(1,16'h20b8,event_id);if(got_error!=0 || available)$fatal(1,"CSR release failed");
        raw_access(1,16'h20b8,event_id);if(got_error!=4)$fatal(1,"Repeated CSR release accepted");
        reset_dut();
        $display("tb_edge_waveform ALL PASS PRE=%0d POST=%0d TEST=%0d checks=%0d",PRE,POST,TEST,checks);$finish;
    end
    initial begin #100000000;$fatal(1,"TIMEOUT waveform");end
endmodule

// Integration check through the existing CSR CDC; no CDC lives in waveform.
module tb_edge_waveform_cdc;
    reg clk=0,s_clk=0;always #5 clk=~clk;always #6.666667 s_clk=~s_clk;
    reg rst_n=0,s_req=0,s_write=0;
    reg [15:0] s_address=0;reg [31:0] s_wdata=0;
    wire s_response;wire [31:0] s_rdata;wire [7:0] s_error;
    wire req,we,response;wire [15:0] address;wire [31:0] wd,rd;wire [7:0] error;
    reg a_new=0,b_new=0,trigger=0;reg [15:0] seq=0;
    reg signed [15:0] ax=0,ay=0,az=0,bx=0,by=0,bz=0;
    reg [63:0] cycles=0;wire available;wire [31:0] id;
    edge_csr_cdc cdc(.s_clk(s_clk),.s_rst_n(rst_n),.s_req(s_req),.s_write(s_write),
        .s_address(s_address),.s_wdata(s_wdata),.s_response(s_response),.s_rdata(s_rdata),.s_error(s_error),
        .d_clk(clk),.d_rst_n(rst_n),.d_req(req),.d_write(we),.d_address(address),.d_wdata(wd),
        .d_response(response),.d_rdata(rd),.d_error(error));
    edge_waveform #(.PRE_SAMPLES(2),.POST_SAMPLES(2),.SAMPLE_HZ(100000),.TEST_MODE(1)) dut(
        .clk(clk),.rst_n(rst_n),.now_cycles(cycles),.now_ms(32'd0),.enable(1'b1),.stop(1'b0),
        .a_new(a_new),.b_new(b_new),.ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),
        .a_seq(seq),.b_seq(seq),.a_bad(1'b0),.b_bad(1'b0),.trigger(trigger),
        .trigger_reason(32'd7),.trigger_frame_id(32'd9),.trigger_frame_start(64'd100),.trigger_frame_end(64'd200),
        .release_req(1'b0),.release_id(32'd0),.release_ack(),.armed(),.capturing(),
        .event_available(available),.event_id(id),.dropped_triggers(),
        .req(req),.write_en(we),.address(address),.wdata(wd),.response(response),.rdata(rd),.error(error));
    reg [31:0] value;reg [7:0] got_error;integer checks=0;
    task bus;
        input wr;input [15:0] addr;input [31:0] data;
        integer limit;
        begin
            @(negedge s_clk);s_req=1;s_write=wr;s_address=addr;s_wdata=data;
            @(negedge s_clk);s_req=0;limit=0;
            while(!s_response && limit<100)begin @(negedge s_clk);limit=limit+1;end
            if(!s_response)$fatal(1,"CDC response timeout %h",addr);
            value=s_rdata;got_error=s_error;checks=checks+1;@(negedge s_clk);
        end
    endtask
    task expect_read;
        input [15:0] addr;input [31:0] expected;
        begin bus(0,addr,0);if(got_error!=0 || value!==expected)$fatal(1,"CDC %h got %h expected %h err %d",addr,value,expected,got_error);end
    endtask
    task point;
        input integer n;input trig;
        begin
            @(negedge clk);ax=n;ay=-n;az=n+100;bx=-n;by=n+200;bz=-n-300;
            seq=n;cycles=n*1000;a_new=1;b_new=1;trigger=trig;
            @(negedge clk);a_new=0;b_new=0;trigger=0;
        end
    endtask
    task data_read;
        input [31:0] selection,expected;
        begin
            bus(1,16'h20c0,selection);if(got_error!=0)$fatal(1,"CDC INDEX failed");
            expect_read(16'h20c4,expected);
        end
    endtask
    initial begin
        repeat(5)@(negedge clk);rst_n=1;repeat(3)@(negedge clk);
        expect_read(16'h2000,32'h57415631);expect_read(16'h20a8,1);
        bus(0,16'h20c4,0);if(got_error!=5)$fatal(1,"CDC unowned DATA visible");
        point(1,0);point(2,0);point(3,0);point(4,1);point(5,0);
        repeat(14)@(negedge clk);if(!available)$fatal(1,"CDC fixture capture failed");
        expect_read(16'h2008,32'h24);expect_read(16'h2048,4);expect_read(16'h204c,4);
        expect_read(16'h2020,0);expect_read(16'h20a4,1);
        data_read(0,32'hfffe0002);data_read(1,32'h00020066);data_read(2,2000);data_read(3,0);data_read(4,0);
        data_read(32'h80000000,32'h00cafffe);data_read(32'h80000001,32'h0002fed2);
        point(60,1);data_read(0,32'hfffe0002);expect_read(16'h2010,1);
        bus(1,16'h20b8,id+1);if(got_error!=4 || !available)$fatal(1,"CDC wrong RELEASE accepted");
        bus(1,16'h20b8,id);if(got_error!=0 || available)$fatal(1,"CDC RELEASE failed");
        bus(1,16'h20bc,1);if(got_error!=0)$fatal(1,"CDC manual trigger failed");
        bus(1,16'h20b4,1);if(got_error!=0)$fatal(1,"CDC STOP failed");
        expect_read(16'h2008,32'h34);expect_read(16'h20a4,2);expect_read(16'h2024,32'h80000000);
        expect_read(16'h2020,32'h1f00);expect_read(16'h20a8,1);
        $display("tb_edge_waveform_cdc ALL PASS 75-to-100MHz checks=%0d",checks);$finish;
    end
    initial begin #1000000;$fatal(1,"CDC waveform TIMEOUT");end
endmodule
