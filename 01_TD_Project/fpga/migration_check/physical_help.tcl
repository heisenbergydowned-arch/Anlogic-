foreach command {route fix_hold optimize_phy_design optimize_post_route} {puts "HELP $command"; catch {help $command}}
puts "OPT COMMANDS: [info commands *opt*]"
exit 0