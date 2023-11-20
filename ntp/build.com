$! Command file to build NTP
$	cc ntp
$	cc tzutil
$	macro/rsx ntoh
$	link/cc ntp+tzutil+ntoh
$! Done
