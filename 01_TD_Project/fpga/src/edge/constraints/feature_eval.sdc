create_clock -name feature_clk -period 10.0 [get_ports clk]
# Isolated core evaluation; no physical board/pin acceptance is claimed.
set_false_path -from [get_ports rst_n]
