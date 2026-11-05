module edge_environment #(
    parameter [31:0] MAX_AGE_MS = 2500,
    // This board installs AHT20 only. Preserve optional BMP raw diagnostics.
    parameter REQUIRE_BMP280 = 1'b0
)(
    input wire clk, rst_n,
    input wire [31:0] now_ms,
    input wire aht_new, aht_present, aht_error,
    input wire [19:0] aht_temperature, aht_humidity,
    input wire bmp_new, bmp_present, bmp_error,
    input wire [19:0] bmp_temperature, bmp_pressure,
    input wire [191:0] bmp_calibration,
    output wire aht_valid, bmp_valid, auxiliary_bad,
    output wire aht_stale, bmp_stale,
    input wire req, write_en,
    input wire [15:0] address,
    output reg response,
    output reg [31:0] read_data,
    output reg [7:0] error
);
    reg aht_seen, bmp_seen, aht_expired, bmp_expired;
    reg [31:0] aht_last_ms, bmp_last_ms, aht_count, bmp_count, snapshot_id;
    reg [639:0] snapshot;
    reg request_seen;
    wire [31:0] aht_age = aht_seen ? now_ms-aht_last_ms : 32'hffffffff;
    wire [31:0] bmp_age = bmp_seen ? now_ms-bmp_last_ms : 32'hffffffff;
    assign aht_stale = !aht_seen || aht_expired || aht_age > MAX_AGE_MS;
    assign bmp_stale = !bmp_seen || bmp_expired || bmp_age > MAX_AGE_MS;
    assign aht_valid = aht_present && !aht_error && !aht_stale && aht_temperature>=20'd52429 && aht_temperature<=20'd707788;
    assign bmp_valid = bmp_present && !bmp_error && !bmp_stale && bmp_calibration[63:48] != 0
        && bmp_calibration[63:48] != 16'hffff && bmp_temperature != 20'h80000 && bmp_pressure != 20'h80000;
    assign auxiliary_bad = !aht_valid || (REQUIRE_BMP280 && !bmp_valid);
    wire [31:0] flags = {24'd0,bmp_stale,bmp_error,bmp_present,aht_stale,aht_error,aht_present,bmp_valid,aht_valid};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            aht_seen<=0; bmp_seen<=0; aht_last_ms<=0; bmp_last_ms<=0;
            aht_expired<=1; bmp_expired<=1;
            aht_count<=0; bmp_count<=0; snapshot_id<=0; snapshot<=0;
            request_seen<=0; response<=0; read_data<=0; error<=0;
        end else begin
            response<=0;
            if (aht_age>MAX_AGE_MS) aht_expired<=1;
            if (bmp_age>MAX_AGE_MS) bmp_expired<=1;
            if (aht_new && aht_present && !aht_error) begin
                aht_seen<=1; aht_expired<=0; aht_last_ms<=now_ms; aht_count<=aht_count+1'b1;
            end
            if (bmp_new && bmp_present && !bmp_error) begin
                bmp_seen<=1; bmp_expired<=0; bmp_last_ms<=now_ms; bmp_count<=bmp_count+1'b1;
            end
            if (!req) request_seen<=0;
            if (req && !request_seen) begin
                request_seen<=1; response<=1; error<=0; read_data<=0;
                if (write_en || address[1:0]!=0 || address<16'h3000 || address>16'h304c) error<=8'h02;
                else if (address==16'h3000) begin
                    snapshot_id<=snapshot_id+1'b1;
                    snapshot<={32'h00000002,bmp_count,aht_count,bmp_calibration,
                        12'd0,bmp_pressure,12'd0,bmp_temperature,12'd0,aht_temperature,
                        12'd0,aht_humidity,bmp_age,aht_age,flags,now_ms,snapshot_id+1'b1,
                        32'h00010000,32'h454e5631};
                    read_data<=32'h454e5631;
                end else read_data<=snapshot[address[6:2]*32+:32];
            end
        end
    end
endmodule
