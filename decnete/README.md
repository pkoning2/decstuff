# DECnet/E related files

Everything here is for DECnet/E V4, RSTS/E V10.1 unless otherwise stated.

1. `evtlog.tsk` -- the standard evtlog with Y2K bugs fixed and support for events that reference TT (async DDCMP) lines/circuits.

2. `ncp.tsk` -- the standard NCP program with TT (async DDCMP) support added.  Refer to file `ncp.txt` for more information.

3. `async-rsts.txt` -- documentation of the asynchronous DDCMP support in RSTS.

4. `async.fth` -- a utility to turn terminal lines on and off in async DDCMP mode.
