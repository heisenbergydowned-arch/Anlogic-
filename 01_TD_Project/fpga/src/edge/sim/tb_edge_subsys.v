`timescale 1ns/1ps
module tb_edge_subsys;
    reg clk=0;always #5 clk=~clk;reg edge_clk=0;always #7 edge_clk=~edge_clk;
    reg edge_rst_n=0;reg [15:0] edge_awaddr=0,edge_araddr=0;reg [31:0] edge_wdata=0;
    reg edge_awvalid=0,edge_wvalid=0,edge_bready=0,edge_arvalid=0,edge_rready=0;
    wire edge_awready,edge_wready,edge_bvalid,edge_arready,edge_rvalid;
    wire [1:0] edge_bresp,edge_rresp;wire [31:0] edge_rdata;
    tri1 reserved_pad,core_dq,sda,scl,board_sda,board_scl;
    wire pwm; tri reserved22;integer i;reg [31:0] value,fid;
    subsys_acq #(.POR_BITS(8),.ACQ_CLK_HZ(100000000),.ENABLE_PS_LINK(1),.ENABLE_FEATURES(1),
        .LINK_TEST_MODE(1),.CONTROL_BENCH_ENABLE(1),.DS_CONV_MS(1),.GRACE_MS(10)) dut(
        .I_sysclk(clk),.I_spi_miso(1'b0),.I_adc_douta(1'b0),.I_adc_busy(1'b0),.I_adc_frstdata(1'b1),
        .IO_j12_19_reserved(reserved_pad),.IO_temp_core_dq(core_dq),.IO_i2c_sda_ext(sda),.IO_i2c_scl_ext(scl),
        .I_fan_fg(1'b1),.O_fan_pwm(pwm),.IO_j12_22_reserved(reserved22),.I_rs485_rx(1'b1),.I_key1(1'b1),.I_key2(1'b1),
        .I_pl_uart_rx(1'b1),.IO_iic_sda(board_sda),.IO_iic_scl(board_scl),
        .edge_clk(edge_clk),.edge_rst_n(edge_rst_n),.edge_awaddr(edge_awaddr),.edge_awvalid(edge_awvalid),.edge_awready(edge_awready),
        .edge_wdata(edge_wdata),.edge_wstrb(4'hf),.edge_wvalid(edge_wvalid),.edge_wready(edge_wready),
        .edge_bresp(edge_bresp),.edge_bvalid(edge_bvalid),.edge_bready(edge_bready),
        .edge_araddr(edge_araddr),.edge_arvalid(edge_arvalid),.edge_arready(edge_arready),
        .edge_rdata(edge_rdata),.edge_rresp(edge_rresp),.edge_rvalid(edge_rvalid),.edge_rready(edge_rready));
    task read;input [15:0] address;reg [31:0] held;begin
        @(negedge edge_clk);edge_araddr=address;edge_arvalid=1;
        do @(posedge edge_clk);while(!edge_arready);
        @(negedge edge_clk);edge_arvalid=0;wait(edge_rvalid);held=edge_rdata;
        repeat(3)begin @(negedge edge_clk);if(!edge_rvalid||held!=edge_rdata)$fatal(1,"AXI read unstable");end
        if(edge_rresp!=0)$fatal(1,"AXI read error %h",address);
        value=held;edge_rready=1;@(negedge edge_clk);edge_rready=0;
    end endtask
    task write;input [15:0] address;input [31:0] data;begin
        // W arrives first, through the live adapter and clock crossing.
        @(negedge edge_clk);edge_wdata=data;edge_wvalid=1;
        do @(posedge edge_clk);while(!edge_wready);
        @(negedge edge_clk);edge_wvalid=0;edge_awaddr=address;edge_awvalid=1;
        do @(posedge edge_clk);while(!edge_awready);
        @(negedge edge_clk);edge_awvalid=0;wait(edge_bvalid);
        repeat(3)@(negedge edge_clk);
        if(edge_bresp!=0)$fatal(1,"AXI write error %h",address);
        edge_bready=1;@(negedge edge_clk);edge_bready=0;
    end endtask
    initial begin
        repeat(400)@(negedge clk);edge_rst_n=1;
        read(0);if(value!=32'h46434231)$fatal(1,"Control identity missing");
        read(16'h1000);if(value!=32'h45444731)$fatal(1,"Feature identity missing");
        read(16'h1040);if(!value[31] || value[16:0]!=0)$fatal(1,"ENV1 capability/staging mask");
        read(16'h3000);if(value!=32'h454e5631)$fatal(1,"ENV1 CDC identity");
        read(16'h304c);if(value!=2)$fatal(1,"ENV1 sole S4b topology");
`ifdef SINGLE_S4B_CSR_ONLY
        write(16'h1050,32'h12345678);read(16'h1050);
        if(value!=32'h12345678)$fatal(1,"Existing mailbox cookie changed");
        $display("tb_edge_subsys ALL PASS asynchronous PS AXI FCB1/EDG1/ENV1 capability and topology CSR only");$finish;
`endif
        read(16'h2000);if(value!=32'h57415631)$fatal(1,"Waveform identity missing");
        read(16'h20a8);if(value!=1)$fatal(1,"Waveform TEST label missing");
        // Exercise the waveform page through GP0 CDC and RAM read backpressure.
        // Real driver diagnostics can trigger a boot-time TEST capture.
        repeat(200000)@(negedge clk);
        read(16'h2008);
        while(value[1])begin repeat(2000)@(negedge clk);read(16'h2008);end
        if(value[2])begin read(16'h200c);write(16'h20b8,value);end
        repeat(140000)@(negedge clk);
        write(16'h20bc,1);value=0;
        while(!value[2])begin repeat(2000)@(negedge clk);read(16'h2008);end
        if(!value[5])$fatal(1,"Waveform status TEST bit missing");
        read(16'h2048);if(value!=256)$fatal(1,"Waveform A count %d",value);
        read(16'h204c);if(value!=256)$fatal(1,"Waveform B count %d",value);
        read(16'h200c);fid=value;if(!fid)$fatal(1,"Waveform event ID zero");
        write(16'h20c0,1);read(16'h20c4);
        if(value[15:0]===16'hxxxx)$fatal(1,"Waveform sample data unknown");
        write(16'h20b8,fid);read(16'h2008);if(value[2])$fatal(1,"Waveform ACK failed");
        write(16'h1050,32'h12345678);read(16'h1050);if(value!=32'h12345678)$fatal(1,"CDC write lost");
        write(16'h000c,1);write(16'h0010,0);write(16'h0014,7);read(8);if(value[7:0]!=0)$fatal(1,"Snapshot command rejected");
        read(16'h0700);if(value[14])$fatal(1,"Unexpected qualification");
        value=0;
        while(value[1:0]==0)begin repeat(2000)@(negedge clk);read(16'h1008);end
        read(16'h1010);fid=value;if(fid==0)$fatal(1,"Frame ID invalid");
        read(16'h1100);if(value!=32'h46524d31)$fatal(1,"Frame header missing");
        read(16'h113c);if(value!=32'h7000)$fatal(1,"TEST/unqualified/transient flags missing %h",value);
        read(16'h1140);if(value!=1)$fatal(1,"Feature configuration");
        for(i=0;i<39;i=i+1)begin read(16'h1200+i*4);if(value[30:23]==255)$fatal(1,"Nonfinite feature %d",i);end
        read(16'h1298);if(value!=32'h45bb8000)$fatal(1,"RPM should be 6000, got %h",value);
        write(16'h1010,fid);write(16'h1010,fid);read(16'h1008);if(value[1:0]!=0)$fatal(1,"Mailbox ACK");
        $display("tb_edge_subsys ALL PASS live acquisition top -> asynchronous PS AXI -> complete 39D frame; PWM inhibited / W8 high-Z, WAV1 capture/read/release");$finish;
    end
    always @(posedge clk)if(edge_rst_n&&(pwm!==1'b0 || reserved22!==1'bz))$fatal(1,"Test data drove real PWM");
    initial begin #1000000000;$fatal(1,"TIMEOUT live acquisition link");end
endmodule
