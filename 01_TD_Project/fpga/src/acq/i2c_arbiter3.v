`timescale 1ns/1ps
module i2c_arbiter3 #(
    parameter CLK_FREQ   = 100000000,
    parameter TIMEOUT_MS = 20
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [2:0]  requests,
    input  wire [20:0] devices,
    input  wire [8:0]  write_counts,
    input  wire [23:0] write_byte0,
    input  wire [23:0] write_byte1,
    input  wire [23:0] write_byte2,
    input  wire [14:0] read_counts,
    output wire        master_req,
    output wire [6:0]  master_dev,
    output wire [2:0]  master_nwr,
    output wire [7:0]  master_wr0,
    output wire [7:0]  master_wr1,
    output wire [7:0]  master_wr2,
    output wire [4:0]  master_nrd,
    input  wire        master_ack,
    input  wire        master_err,
    input  wire        master_rd_valid,
    output wire [2:0]  acknowledgements,
    output wire [2:0]  errors,
    output wire [2:0]  read_valid,
    output reg         master_reset_n
);

    localparam [31:0] MS_DIV        = ((CLK_FREQ / 1000) < 1) ? 32'd1 : (CLK_FREQ / 1000);
    localparam [31:0] TIMEOUT_TICKS = MS_DIV * TIMEOUT_MS;

    localparam [2:0] GAP_LOAD = 3'd1;
    localparam [3:0] RST_LOAD = 4'd3;

    localparam [1:0] A_IDLE   = 2'd0;
    localparam [1:0] A_ACTIVE = 2'd1;
    localparam [1:0] A_GAP    = 2'd2;
    localparam [1:0] A_RESET  = 2'd3;

    reg [1:0]  st;
    reg [1:0]  owner;
    reg [1:0]  rr_ptr;
    reg [31:0] wd_cnt;
    reg [2:0]  gap_cnt;
    reg [3:0]  rst_cnt;

    wire [1:0] p1 = (rr_ptr == 2'd2) ? 2'd0 : (rr_ptr + 2'd1);
    wire [1:0] p2 = (rr_ptr == 2'd0) ? 2'd2 : (rr_ptr - 2'd1);

    reg [1:0] winner;
    reg       win_v;

    always @* begin
        if (requests[rr_ptr]) begin
            winner = rr_ptr;
            win_v  = 1'b1;
        end else if (requests[p1]) begin
            winner = p1;
            win_v  = 1'b1;
        end else if (requests[p2]) begin
            winner = p2;
            win_v  = 1'b1;
        end else begin
            winner = 2'd0;
            win_v  = 1'b0;
        end
    end

    reg [6:0] mdev;
    reg [2:0] mnwr;
    reg [7:0] mw0;
    reg [7:0] mw1;
    reg [7:0] mw2;
    reg [4:0] mnrd;

    always @* begin
        case (owner)
        2'd0: begin
            mdev = devices[6:0];
            mnwr = write_counts[2:0];
            mw0  = write_byte0[7:0];
            mw1  = write_byte1[7:0];
            mw2  = write_byte2[7:0];
            mnrd = read_counts[4:0];
        end
        2'd1: begin
            mdev = devices[13:7];
            mnwr = write_counts[5:3];
            mw0  = write_byte0[15:8];
            mw1  = write_byte1[15:8];
            mw2  = write_byte2[15:8];
            mnrd = read_counts[9:5];
        end
        default: begin
            mdev = devices[20:14];
            mnwr = write_counts[8:6];
            mw0  = write_byte0[23:16];
            mw1  = write_byte1[23:16];
            mw2  = write_byte2[23:16];
            mnrd = read_counts[14:10];
        end
        endcase
    end

    assign master_req = (st == A_ACTIVE);
    assign master_dev = (st == A_ACTIVE) ? mdev : 7'd0;
    assign master_nwr = (st == A_ACTIVE) ? mnwr : 3'd0;
    assign master_wr0 = (st == A_ACTIVE) ? mw0  : 8'd0;
    assign master_wr1 = (st == A_ACTIVE) ? mw1  : 8'd0;
    assign master_wr2 = (st == A_ACTIVE) ? mw2  : 8'd0;
    assign master_nrd = (st == A_ACTIVE) ? mnrd : 5'd0;

    wire       wd_fire  = (st == A_ACTIVE) && (!master_ack) && (wd_cnt >= TIMEOUT_TICKS);
    wire [2:0] ack_mask = (st == A_ACTIVE) ? (3'b001 << owner) : 3'b000;

    assign acknowledgements = (master_ack || wd_fire) ? ack_mask : 3'b000;
    assign errors           = (master_err || wd_fire) ? ack_mask : 3'b000;
    assign read_valid       = master_rd_valid ? ack_mask : 3'b000;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st             <= A_IDLE;
            owner          <= 2'd0;
            rr_ptr         <= 2'd0;
            wd_cnt         <= 32'd0;
            gap_cnt        <= 3'd0;
            rst_cnt        <= 4'd0;
            master_reset_n <= 1'b1;
        end else begin
            case (st)

            A_IDLE: begin
                master_reset_n <= 1'b1;
                if (win_v) begin
                    owner  <= winner;
                    rr_ptr <= (winner == 2'd2) ? 2'd0 : (winner + 2'd1);
                    wd_cnt <= 32'd0;
                    st     <= A_ACTIVE;
                end
            end

            A_ACTIVE: begin
                if (master_ack) begin
                    gap_cnt <= GAP_LOAD;
                    st      <= A_GAP;
                end else if (!requests[owner]) begin
                    master_reset_n <= 1'b0;
                    rst_cnt        <= RST_LOAD;
                    st             <= A_RESET;
                end else if (wd_cnt >= TIMEOUT_TICKS) begin
                    master_reset_n <= 1'b0;
                    rst_cnt        <= RST_LOAD;
                    st             <= A_RESET;
                end else begin
                    wd_cnt <= wd_cnt + 32'd1;
                end
            end

            A_GAP: begin
                master_reset_n <= 1'b1;
                if (gap_cnt == 3'd0) begin
                    st <= A_IDLE;
                end else begin
                    gap_cnt <= gap_cnt - 3'd1;
                end
            end

            A_RESET: begin
                master_reset_n <= 1'b0;
                if (rst_cnt == 4'd0) begin
                    master_reset_n <= 1'b1;
                    gap_cnt        <= GAP_LOAD;
                    st             <= A_GAP;
                end else begin
                    rst_cnt <= rst_cnt - 4'd1;
                end
            end

            default: st <= A_IDLE;
            endcase
        end
    end
endmodule
