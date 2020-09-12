; Fix invalid address in point to point hello messages introduced
; in RSTS 9.6 (or possibly earlier), DECnet/E V4.x.
;
; This is a Monitor patch
;
File to patch? <LF>
Enter the name of the module in the SIL to be patched: TRN
Base address? ROUDDC@OVR
Offset address? 4224
 Base	Offset  Old     New?
??????	004224	016500	? 16502
??????	004226	000032	? <LF>
??????	004230	012760	? 12762
??????	004232	000006	? <LF>
??????	004234	000006	? <LF>
??????	004236	112724	? ^C
