; Fix DMC startup problem (buffers assigned before startup done)
; in RSTS 9.2.  (This bug was fixed in RSTS 9.3.)
;
; This is a Monitor patch
File to patch? <LF>
Module name? XVR
Base address? XMDVRM
Offset address? 3522
 Base	Offset  Old     New?
??????	003522	105262	? 137
??????	003524	000017	? XVRPAT
??????	003526	116103	? ^Z
Offset address? ^Z
Base address? XVRPAT
Offset address? 0
 Base	Offset  Old     New?
??????	000000	000000	? 105262
??????	000002	000000	? 17
??????	000004	000000	? 32761
??????	000006	000000	? 1000
??????	000010	000000	? 10
??????	000012	000000	? 1002
??????	000014	000000	? 137
??????	000016	000000	? XMDVRM+3526
??????	000020	000000	? 207
??????	000022	??????	? ^C