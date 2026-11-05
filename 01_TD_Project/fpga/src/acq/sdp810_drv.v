`timescale 1ns/1ps
module sdp810_drv #(
    parameter CLK_FREQ           = 100000000,
    parameter POLL_MS            = 10,
    parameter STALE_MS           = 100,
    parameter RETRY_MS           = 100,
    parameter REQUEST_TIMEOUT_MS = 100
)(
    input  wire               clk,
    input  wire               rst_n,
    output reg                i2c_req,
    output wire [6:0]         i2c_dev,
    output reg  [2:0]         i2c_nwr,
    output reg  [7:0]         i2c_wr0,
    output reg  [7:0]         i2c_wr1,
    output reg  [7:0]         i2c_wr2,
    output reg  [4:0]         i2c_nrd,
    input  wire               i2c_ack,
    input  wire               i2c_err,
    input  wire               i2c_rd_valid,
    input  wire [7:0]         i2c_rd_data,
    input  wire [4:0]         i2c_rd_idx,
    output reg                sample_valid,
    output reg  signed [15:0] pressure_raw,
    output reg  signed [15:0] temperature_raw,
    output reg  [15:0]        scale_factor,
    output reg  [31:0]        product_number,
    output reg  [63:0]        serial_number,
    output reg                present,
    output reg                err,
    output wire               stale,
    output reg  [31:0]        age_ms,
    output reg  [7:0]         error_code
);

    localparam [31:0] MS_DIV   = ((CLK_FREQ / 1000) < 1) ? 32'd1 : (CLK_FREQ / 1000);
    localparam [31:0] T_POR    = MS_DIV * 32'd20;
    localparam [31:0] T_RSTW   = MS_DIV;
    localparam [31:0] T_IDW    = MS_DIV;
    localparam [31:0] T_STRW   = MS_DIV * 32'd20;
    localparam [31:0] T_POLL   = MS_DIV * ((POLL_MS < 1) ? 1 : POLL_MS);
    localparam [31:0] T_RETRY  = MS_DIV * RETRY_MS;
    localparam [31:0] T_REQ_TO = MS_DIV * REQUEST_TIMEOUT_MS;
    localparam [31:0] T_STALE  = STALE_MS;

    localparam [7:0] EC_OK      = 8'h00;
    localparam [7:0] EC_BUS     = 8'h01;
    localparam [7:0] EC_TIMEOUT = 8'h02;
    localparam [7:0] EC_FRAME   = 8'h03;
    localparam [7:0] EC_CRC     = 8'h04;
    localparam [7:0] EC_MODEL   = 8'h05;
    localparam [7:0] EC_SCALE   = 8'h06;
    localparam [7:0] EC_RANGE   = 8'h07;

    localparam [3:0] S_POR  = 4'd0;
    localparam [3:0] S_RST  = 4'd1;
    localparam [3:0] S_RSTW = 4'd2;
    localparam [3:0] S_ID1  = 4'd3;
    localparam [3:0] S_ID2  = 4'd4;
    localparam [3:0] S_IDW  = 4'd5;
    localparam [3:0] S_IDR  = 4'd6;
    localparam [3:0] S_IDV  = 4'd7;
    localparam [3:0] S_STR  = 4'd8;
    localparam [3:0] S_STRW = 4'd9;
    localparam [3:0] S_POLW = 4'd10;
    localparam [3:0] S_MRD  = 4'd11;
    localparam [3:0] S_MRV  = 4'd12;
    localparam [3:0] S_ERRW = 4'd13;

    assign i2c_dev = 7'h25;

    reg [3:0]  st;
    reg [31:0] tmr;
    reg [31:0] req_to;
    reg [4:0]  rx_len;
    reg [4:0]  rx_next;
    reg [4:0]  rx_cnt;
    reg        rx_bad;
    reg [7:0]  rxb [0:17];

    function [7:0] sdp_crc;
        input [15:0] word_data;
        integer  bit_index;
        reg [7:0] crc_value;
        begin
            crc_value = 8'hFF ^ word_data[15:8];
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
                crc_value = crc_value[7] ? ((crc_value << 1) ^ 8'h31) : (crc_value << 1);
            crc_value = crc_value ^ word_data[7:0];
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
                crc_value = crc_value[7] ? ((crc_value << 1) ^ 8'h31) : (crc_value << 1);
            sdp_crc = crc_value;
        end
    endfunction

    wire [7:0] crc_p = sdp_crc({rxb[0], rxb[1]});
    wire [7:0] crc_t = sdp_crc({rxb[3], rxb[4]});
    wire [7:0] crc_s = sdp_crc({rxb[6], rxb[7]});

    wire signed [16:0] pr_ext = {rxb[0][7], rxb[0], rxb[1]};
    wire        [16:0] pr_abs = pr_ext[16] ? (~pr_ext + 17'd1) : pr_ext;

    wire meas_frame_ok = (rx_len == 5'd9) && (rx_cnt == rx_len) && (!rx_bad);
    wire meas_crc_ok   = (crc_p == rxb[2]) && (crc_t == rxb[5]) && (crc_s == rxb[8]);
    wire meas_scale_ok = ({rxb[6], rxb[7]} == 16'd60);
    wire meas_range_ok = (pr_abs <= 17'd30000);
    wire meas_ok       = (st == S_MRV) && meas_frame_ok && meas_crc_ok &&
                         meas_scale_ok && meas_range_ok;

    wire [7:0]  ic0 = sdp_crc({rxb[0],  rxb[1]});
    wire [7:0]  ic1 = sdp_crc({rxb[3],  rxb[4]});
    wire [7:0]  ic2 = sdp_crc({rxb[6],  rxb[7]});
    wire [7:0]  ic3 = sdp_crc({rxb[9],  rxb[10]});
    wire [7:0]  ic4 = sdp_crc({rxb[12], rxb[13]});
    wire [7:0]  ic5 = sdp_crc({rxb[15], rxb[16]});

    wire id_frame_ok = (rx_len == 5'd18) && (rx_cnt == rx_len) && (!rx_bad);
    wire id_crc_ok   = (ic0 == rxb[2])  && (ic1 == rxb[5])  && (ic2 == rxb[8]) &&
                       (ic3 == rxb[11]) && (ic4 == rxb[14]) && (ic5 == rxb[17]);
    wire [31:0] id_prod = {rxb[0], rxb[1], rxb[3], rxb[4]};
    wire [63:0] id_ser  = {rxb[6], rxb[7], rxb[9], rxb[10],
                           rxb[12], rxb[13], rxb[15], rxb[16]};
    wire id_model_ok = (id_prod[31:8] == 24'h03020A);

    reg [31:0] ms_cnt;
    reg        have_sample;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ms_cnt      <= 32'd0;
            age_ms      <= 32'd0;
            have_sample <= 1'b0;
        end else begin
            if (ms_cnt == (MS_DIV - 32'd1)) begin
                ms_cnt <= 32'd0;
                if (age_ms != 32'hFFFFFFFF)
                    age_ms <= age_ms + 32'd1;
            end else begin
                ms_cnt <= ms_cnt + 32'd1;
            end
            if (meas_ok) begin
                age_ms      <= 32'd0;
                have_sample <= 1'b1;
            end
        end
    end

    assign stale = (!have_sample) || (age_ms >= T_STALE);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st             <= S_POR;
            tmr            <= T_POR;
            req_to         <= 32'd0;
            i2c_req        <= 1'b0;
            i2c_nwr        <= 3'd0;
            i2c_wr0        <= 8'd0;
            i2c_wr1        <= 8'd0;
            i2c_wr2        <= 8'd0;
            i2c_nrd        <= 5'd0;
            rx_len         <= 5'd0;
            rx_next        <= 5'd0;
            rx_cnt         <= 5'd0;
            rx_bad         <= 1'b0;
            sample_valid   <= 1'b0;
            pressure_raw   <= 16'sd0;
            temperature_raw<= 16'sd0;
            scale_factor   <= 16'd0;
            product_number <= 32'd0;
            serial_number  <= 64'd0;
            present        <= 1'b0;
            err            <= 1'b1;
            error_code     <= EC_OK;
        end else begin
            sample_valid <= 1'b0;
            i2c_req      <= 1'b0;
            case (st)

            S_POR: begin
                if (tmr == 32'd0) begin
                    st     <= S_RST;
                    req_to <= 32'd0;
                end else begin
                    tmr <= tmr - 32'd1;
                end
            end

            S_RST: begin
                i2c_req <= 1'b1;
                i2c_nwr <= 3'd2;
                i2c_wr0 <= 8'h3F;
                i2c_wr1 <= 8'hF9;
                i2c_wr2 <= 8'd0;
                i2c_nrd <= 5'd0;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err        <= 1'b1;
                        error_code <= EC_BUS;
                        present    <= 1'b0;
                        st         <= S_ERRW;
                        tmr        <= T_RETRY;
                    end else begin
                        st  <= S_RSTW;
                        tmr <= T_RSTW;
                    end
                end else if (req_to >= T_REQ_TO) begin
                    i2c_req    <= 1'b0;
                    err        <= 1'b1;
                    error_code <= EC_TIMEOUT;
                    present    <= 1'b0;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else begin
                    req_to <= req_to + 32'd1;
                end
            end

            S_RSTW: begin
                if (tmr == 32'd0) begin
                    st     <= S_ID1;
                    req_to <= 32'd0;
                end else begin
                    tmr <= tmr - 32'd1;
                end
            end

            S_ID1: begin
                i2c_req <= 1'b1;
                i2c_nwr <= 3'd2;
                i2c_wr0 <= 8'h36;
                i2c_wr1 <= 8'h7C;
                i2c_wr2 <= 8'd0;
                i2c_nrd <= 5'd0;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err        <= 1'b1;
                        error_code <= EC_BUS;
                        present    <= 1'b0;
                        st         <= S_ERRW;
                        tmr        <= T_RETRY;
                    end else begin
                        st     <= S_ID2;
                        req_to <= 32'd0;
                    end
                end else if (req_to >= T_REQ_TO) begin
                    i2c_req    <= 1'b0;
                    err        <= 1'b1;
                    error_code <= EC_TIMEOUT;
                    present    <= 1'b0;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else begin
                    req_to <= req_to + 32'd1;
                end
            end

            S_ID2: begin
                i2c_req <= 1'b1;
                i2c_nwr <= 3'd2;
                i2c_wr0 <= 8'hE1;
                i2c_wr1 <= 8'h02;
                i2c_wr2 <= 8'd0;
                i2c_nrd <= 5'd0;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err        <= 1'b1;
                        error_code <= EC_BUS;
                        present    <= 1'b0;
                        st         <= S_ERRW;
                        tmr        <= T_RETRY;
                    end else begin
                        st  <= S_IDW;
                        tmr <= T_IDW;
                    end
                end else if (req_to >= T_REQ_TO) begin
                    i2c_req    <= 1'b0;
                    err        <= 1'b1;
                    error_code <= EC_TIMEOUT;
                    present    <= 1'b0;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else begin
                    req_to <= req_to + 32'd1;
                end
            end

            S_IDW: begin
                if (tmr == 32'd0) begin
                    rx_len  <= 5'd18;
                    rx_next <= 5'd0;
                    rx_cnt  <= 5'd0;
                    rx_bad  <= 1'b0;
                    st      <= S_IDR;
                    req_to  <= 32'd0;
                end else begin
                    tmr <= tmr - 32'd1;
                end
            end

            S_IDR: begin
                i2c_req <= 1'b1;
                i2c_nwr <= 3'd0;
                i2c_nrd <= 5'd18;
                if (i2c_rd_valid) begin
                    if ((!rx_bad) && (i2c_rd_idx == rx_next) && (rx_next < rx_len)) begin
                        rxb[i2c_rd_idx] <= i2c_rd_data;
                        rx_next         <= rx_next + 5'd1;
                        rx_cnt          <= rx_cnt + 5'd1;
                    end else begin
                        rx_bad <= 1'b1;
                    end
                end
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err        <= 1'b1;
                        error_code <= EC_BUS;
                        present    <= 1'b0;
                        st         <= S_ERRW;
                        tmr        <= T_RETRY;
                    end else begin
                        st <= S_IDV;
                    end
                end else if (req_to >= T_REQ_TO) begin
                    i2c_req    <= 1'b0;
                    err        <= 1'b1;
                    error_code <= EC_TIMEOUT;
                    present    <= 1'b0;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else begin
                    req_to <= req_to + 32'd1;
                end
            end

            S_IDV: begin
                if (!id_frame_ok) begin
                    err        <= 1'b1;
                    error_code <= EC_FRAME;
                    present    <= 1'b0;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else if (!id_crc_ok) begin
                    err        <= 1'b1;
                    error_code <= EC_CRC;
                    present    <= 1'b0;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else if (!id_model_ok) begin
                    err        <= 1'b1;
                    error_code <= EC_MODEL;
                    present    <= 1'b0;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else begin
                    product_number <= id_prod;
                    serial_number  <= id_ser;
                    present        <= 1'b1;
                    st             <= S_STR;
                    req_to         <= 32'd0;
                end
            end

            S_STR: begin
                i2c_req <= 1'b1;
                i2c_nwr <= 3'd2;
                i2c_wr0 <= 8'h36;
                i2c_wr1 <= 8'h1E;
                i2c_wr2 <= 8'd0;
                i2c_nrd <= 5'd0;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err        <= 1'b1;
                        error_code <= EC_BUS;
                        present    <= 1'b0;
                        st         <= S_ERRW;
                        tmr        <= T_RETRY;
                    end else begin
                        st  <= S_STRW;
                        tmr <= T_STRW;
                    end
                end else if (req_to >= T_REQ_TO) begin
                    i2c_req    <= 1'b0;
                    err        <= 1'b1;
                    error_code <= EC_TIMEOUT;
                    present    <= 1'b0;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else begin
                    req_to <= req_to + 32'd1;
                end
            end

            S_STRW: begin
                if (tmr == 32'd0) begin
                    st  <= S_POLW;
                    tmr <= 32'd0;
                end else begin
                    tmr <= tmr - 32'd1;
                end
            end

            S_POLW: begin
                if (tmr == 32'd0) begin
                    rx_len  <= 5'd9;
                    rx_next <= 5'd0;
                    rx_cnt  <= 5'd0;
                    rx_bad  <= 1'b0;
                    st      <= S_MRD;
                    req_to  <= 32'd0;
                end else begin
                    tmr <= tmr - 32'd1;
                end
            end

            S_MRD: begin
                i2c_req <= 1'b1;
                i2c_nwr <= 3'd0;
                i2c_nrd <= 5'd9;
                if (i2c_rd_valid) begin
                    if ((!rx_bad) && (i2c_rd_idx == rx_next) && (rx_next < rx_len)) begin
                        rxb[i2c_rd_idx] <= i2c_rd_data;
                        rx_next         <= rx_next + 5'd1;
                        rx_cnt          <= rx_cnt + 5'd1;
                    end else begin
                        rx_bad <= 1'b1;
                    end
                end
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err        <= 1'b1;
                        error_code <= EC_BUS;
                        present    <= 1'b0;
                        st         <= S_ERRW;
                        tmr        <= T_RETRY;
                    end else begin
                        st <= S_MRV;
                    end
                end else if (req_to >= T_REQ_TO) begin
                    i2c_req    <= 1'b0;
                    err        <= 1'b1;
                    error_code <= EC_TIMEOUT;
                    present    <= 1'b0;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else begin
                    req_to <= req_to + 32'd1;
                end
            end

            S_MRV: begin
                if (!meas_frame_ok) begin
                    err        <= 1'b1;
                    error_code <= EC_FRAME;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else if (!meas_crc_ok) begin
                    err        <= 1'b1;
                    error_code <= EC_CRC;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else if (!meas_scale_ok) begin
                    err        <= 1'b1;
                    error_code <= EC_SCALE;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else if (!meas_range_ok) begin
                    err        <= 1'b1;
                    error_code <= EC_RANGE;
                    st         <= S_ERRW;
                    tmr        <= T_RETRY;
                end else begin
                    pressure_raw    <= {rxb[0], rxb[1]};
                    temperature_raw <= {rxb[3], rxb[4]};
                    scale_factor    <= {rxb[6], rxb[7]};
                    sample_valid    <= 1'b1;
                    err             <= 1'b0;
                    error_code      <= EC_OK;
                    st              <= S_POLW;
                    tmr             <= T_POLL;
                end
            end

            S_ERRW: begin
                if (tmr == 32'd0) begin
                    st     <= S_RST;
                    req_to <= 32'd0;
                end else begin
                    tmr <= tmr - 32'd1;
                end
            end

            default: st <= S_POR;
            endcase
        end
    end
endmodule
