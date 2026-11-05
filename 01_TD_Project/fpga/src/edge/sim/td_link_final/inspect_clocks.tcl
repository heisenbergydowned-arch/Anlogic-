import_device dr1_90.db -package DR1M90GEG400 -speed 2
import_db cooling_link_gate.db
start_timer
puts "ALLCLOCKS=[get_clocks *]"
puts "SYS=[get_clocks sysclk]"
puts "ALIAS75=[get_clocks clk_75m]"
puts "ORIGINAL75=[get_clocks {system/design_0_inst/design_0_pll_75m_Inst/dr1_phy_pll_1f386b1db2c3_Inst/u_DR1_PHY_PLL.clkc[0]}]"
puts "INSPECT_COMPLETE"
exit
