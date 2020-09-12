!
! Patch to make retry work on transmit queue full status.
! This patch is for DECnet/E V4.1, possible for older versions as
! well.
!
! This patch is for NCP, normally found in DECNET$:NCP.TSK.
!
! Paul Koning, 14-Aug-2020  GPK
!
File to patch?
Base address? $NXMIT
Offset address? 20
 Base	Offset  Old     New?
??????	000020	103012	? 103007
??????	000022	??????	? ^C
