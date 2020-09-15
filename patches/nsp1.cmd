! Fix performance issue with one-way traffic flow.  This issue is seen
! in SIMH due to the execution timing, but it is at least in theory a
! possible issue on real hardware as well.
!
! This is a Monitor patch for DECnet/E V4, RSTS/E V10.1.
!
! Paul Koning, 2-May-16
!
File to patch? <LF>
Module name? NSP
Base address? NSP1@OVR
Offset address? 13054
 Base	Offset  Old     New?
??????	013054	005200	? 4737
??????	013056	005001	? NSPPAT@OVR
??????	013060	032702	? ^Z
Offset address? ^Z
Base address? NSPPAT@OVR
Offset address? 0
 Base	Offset  Old     New?
??????	000000	000000	? 16301
??????	000002	000000	? 2
??????	000004	000000	? 4737
??????	000006	000000	? NSP1@OVR+12702
??????	000010	000000	? 5200
??????	000012	000000	? 5001
??????	000014	000000	? 207
??????	000016	??????	? ^Z
Offset address? ^C
