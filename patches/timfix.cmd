!
!  Fix UU.DAT (set system date/time) so it correctly sets
!  seconds to zero.
!
!  This is a Monitor patch
!
!  Paul Koning, 12-Sep-20
!
File to patch? <LF>
Module name? OVR
Base address? STLSYS
Offset address? 330
 Base	Offset  Old     New?
??????	000330	012737	? 112737
??????	000332	000074	? ^C
