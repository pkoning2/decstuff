! Fix issues with DEUNA driver
!
! Three items:
! 1. Non-zero unit number was handled as unit zero.
! 2. Close would mishandle non-zero unit numbers.
! 3. User receive completion did not give the buffers back to active receive.
!
!  This is a Monitor patch, developed for V10.1; it might work on older versions.
!
!  Paul Koning, 20-Nov-23
!
File to patch? <LF>
Module name? UNA
Base address? XEDVRM@OVR
Offset address? 2170
 Base	Offset  Old     New?
??????	002170	016661	? 116661
??????	002172	000004	? ^Z
Offset address? 2404
 Base	Offset  Old     New?
??????	002404	016100	? 10005
??????	002406	000004	? 16100
??????	002410	116105	? 4
??????	002412	177767	? 240
??????	002414	016505	? ^Z
Offset address? 6002
 Base	Offset  Old     New?
??????	006002	004767	? 4737
??????	006004	006606	? PATCH@RSTS
??????	006006	012677	? ^Z
Offset address? ^Z
Base address? ^Z
Module name? RSTS
Base address? PATCH
Offset address? 0
 Base	Offset  Old	New?
??????	000000	000000	? 4737
??????	000002	000000	? XEDVRM@OVR+14614
??????	000004	000000	? 12737
??????	000006	000000	? 34240
??????	000010	000000	? 177776
??????	000012	000000	? 4737
??????	000014	000000	? XEDVRM@OVR+15336
??????	000016	000000	? 12737
??????	000020	000000	? 34140
??????	000022	000000	? 177776
??????	000024	000000	? 207
??????	000026	000000	? ^C
