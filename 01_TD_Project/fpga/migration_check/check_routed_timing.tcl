# A successful tool exit alone is insufficient for a release bitstream.
proc cooling_verify_routed_text {report} {
 if {![regexp {Confidence\s*:\s*Routed} $report]} {error "timing confidence is not Routed"}
 if {![regexp {Check Corner\s*:\s*Both} $report]} {error "both timing corners were not checked"}
 if {![regexp {SWNS:\s*(-?[0-9.]+)ns} $report unused swns] || ![regexp {HWNS:\s*(-?[0-9.]+)ns} $report unused hwns]} {error "routed report missing SWNS/HWNS"}
 if {$swns < 0 || $hwns < 0} {error "routed timing failed: SWNS=$swns HWNS=$hwns; bitgen blocked"}
 if {![regexp {STA coverage\s*:\s*([0-9.]+)%} $report unused coverage] || $coverage < 99.9} {error "routed STA coverage is missing or below 99.9%; bitgen blocked"}
 if {![regexp {Period Check WNS:\s*(-?[0-9.]+)ns} $report unused period_wns] || $period_wns < 0} {error "period check failed or missing; bitgen blocked"}
 foreach {suffix expected} {HP0 150 GP0S 75 GP1S 150 HP1 150} {
   set pattern [format {\n\s*clk[0-9]+:\s*([0-9.]+)\s+([0-9]+)\s+[^\n]*GEN_PL_%s(?:\s|\n)} $suffix]
   if {![regexp $pattern $report unused actual fanout] || $fanout < 1 || abs($actual-$expected)>0.1} {error "native PS GEN_PL_$suffix missing, unused or wrong frequency; bitgen blocked"}
 }
 return [dict create SWNS $swns HWNS $hwns coverage $coverage period_wns $period_wns]
}
proc cooling_verify_routed_file {path} {
 set f [open $path r]
 set report [read $f]
 close $f
 set result [cooling_verify_routed_text $report]
 puts "VM_ROUTED_TIMING_PASS: $result"
 return $result
}