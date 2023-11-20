$! Start NTP daemon
$ _assign/system/replace SY:[0,123] NTP$:
$! --- change the line below to specify the Ethernet device to use
$ _assign/system/replace XE1: NTP$IF:
$! Enable output so the NTP startup message is displayed
$ set echo
$ _run NTP$:NTP
$ set noecho
$!
