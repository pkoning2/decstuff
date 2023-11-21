# NTP client for RSTS/E

This is a simple NTP (Internet Network Time Protocol) client for RSTS/E.
Since RSTS does not have IP support, this client handles NTP broadcast
time announcements but it does not implement the more common
request/response handshake.  The broadcast scheme, because it doesn't
allow for measurement of the network delays, does not produce as high
an accuracy as the request/response version does.  But given that
RSTS/E has rather coarse clock resolution -- 10 ms best case -- the
broadcast is easily adequate.

To use this you will need an NTP client on the LAN to which the RSTS
system is connected, with periodic time broadcasts enabled.
The "chronyd" NTP implementation can easily be configured to do this
using the `broadcast` statement in the chrony.conf file.  I believe
"ntpd" can also do this but I have not tested that.

Please note:

Both RSTS Ethernet drivers have bugs that require patches.  Be sure to install
the patch in `patches/xedvr.cmd` and/or `patches/xhdvr.cmd`.

Contents:
* ntp.c -- the main program.
* tzutil.c -- a set of functions for manipulating time encodings.
* tzutil.h -- a header file for the above.
* ntoh.mac -- functions for converting from "network byte order".
* start.com -- a sample RSTS/E startup command file for NTP.
* build.com -- a sample command file to build NTP from source.
* ntp.tsk -- a pre-built binary for NTP.

## Building

You can use the prebuilt `ntp.tsk` but it's easy to build from source if you
prefer.  You need DEC C for this.  To build, do `@build.com`.  Note that the
code defaults to 60 Hz clock frequency.  To use a different value, supply the
definition when compiling `tzutil.c`, for example:

    cc /define="HERTZ 50" tzutil

## Installing

NTP expects some files in directory [0,123].  Create that on the system
disk and copy into it:
* ntp.tsk
* start.com
* tz.dat

tz.dat is the timezone data file for the timezone in which your RSTS system
lives.  You can get this from the Internet time zone data repository, but
on a typical Unix system you will have a full set of timezone files, typically
in `/usr/share/zoneinfo`.  For example, if you are in the USA Eastern time zone,
the likely correct timezone file is in `Americas/New_York`.  Copy that file,
in binary  mode, to your RSTS system and name it `[0,123]tz.dat`.

You will probably need to edit [0,123]start.com.  It defines logical name
`NTP$IF` to be the RSTS device designator of the Ethernet interface to use.
Edit that as needed.

## Starting NTP

To run NTP, execute `@[0,123]start.com`.  You can add that line to the
standard system startup file `[0,1]start.com` to start NTP at system startup.

NTP reports the current time at startup.  It then detaches and runs
until killed or until system shutdown.  At this point it listens for
NTP broadcast messages and will update the system time
(to the resolution available with RSTS) accordingly.  If the current zone
offset changes
(start of end of "daylight savings time" or "summer time") that is reflected
in the RSTS time.

To minimize latency issues, NTP runs with slightly elevated priority and locked in memory.

## Messages

If NTP adjusts the RSTS time by more than one second it generates a message
using the OMS subsystem.  If OMS is not running, nothing is reported.  The message looks like this:

    >>>>>>>>>>>>>>>  OMS V10.1-A  20-Nov-23 05:00 PM  <<<<<<<<<<<<<<<
    Message 1558 from NTP, user [1,2], Detached, job 2
    Time updated to 20-Nov-2023  5:00:44.83 pm EST (-5:00), stratum 1, source GPS

