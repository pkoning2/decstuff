! Patch to fix incorrect display of DMR line card configuration
! in HARDWARE LIST option.
!
! This patch is for RSTS 10.1.
!
! Paul Koning, 19-Aug-2016
!
File to patch? INIT.SYS
Base address? HAR
Offset address? 6166
 Base	Offset  Old     New?
??????	006166	??????	? <LF>
??????	006170	000020	? 40
??????	006172	177717	? <LF>
??????	006174	??????	? <LF>
??????	006176	??????	? <LF>
??????	006200	000000	? <LF>
??????	006202	177717	? <LF>
??????	006204	??????	? <LF>
??????	006206	??????	? <LF>
??????	006210	000060	? <LF>
??????	006212	177717	? <LF>
??????	006214	??????	? <LF>
??????	006216	??????	? <LF>
??????	006220	000040	? 20
??????	006222	177717	? ^C
