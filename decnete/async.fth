\
\			A S Y N C . F T H
\
\ This is a small FORTH utility to control async DDCMP on a terminal
\ line in RSTS/E V10.1.  While async DDCMP can be used with application
\ programs, here we use it as a DECnet line.
\
\ Edit history:
\
\	22-Jul-19	GPK	Initial version.

\ To compile ASYNC, you also need COMMON.FTH (a FORTH translation of
\ COMMON.MAC) from the FORTH optional install in the RSTS/E kit.

\ Lifted from COMMON.FTH since that doesn't seem to be on the kit.
base @

0 variable dot
: .dsect dot ! ;
: .bsect 1 .dsect ;
: ?b dot @ 1 and -dup
  if dot +! ." Boundary error in " latest id. ."  at " dot @ o. cr
  endif ;
: .fillb dot +! ;
: .fillw ?b 2* .fillb ;
: .val dot @ constant ;
: .blkb .val .fillb ;
: .blkw ?b 2* .blkb ;
: .byte 1 .blkb ;
: .word 1 .blkw ;
: .bit dot @ .blkb ;
: .nobit dot @ .fillb ;

octal

\ XRB and FIRQB sizes

40 constant	FQBSIZ	\ Size of FIRQB in bytes
16 constant	XRBSIZ	\ Size of XRB in bytes

\ Some monitor calls

104014 constant	.SPEC	\ Special function
104060 constant	.MESAG	\ Message send/receive

\ Job Unique Low Memory Layout

0	.dsect

30	.fillw		\ Job controlled
15	.fillw		\ Reserved for monitor context use
30	.fillw		\ Reserved for monitor FPP context use
103	.fillw		\ Job's SP stack area
	.val	USRSP	\ Default job SP stack setting
	.word	RSTS-KEY \ Keyword of job's current status
fqbsiz	.blkb	FIRQB	\ File request queue block
xrbsiz	.blkb	XRB	\ Transfer control block
200	.blkb	CORCMN	\ CCL line COMMON
26	.fillw		\ Job controlled
	.word	USRPPN	\ User's assignable PPN
	.word	USRPRT	\ User's assignable protection code
4 4 *	.blkw	USRLOG	\ User's logical device table
	.val	NSTORG	\ End of low memory fixed layout

\ Transfer Control Block -- XRB

xrb	.dsect

	.word	XRLEN	\ Length of I/O buffer in bytes
	.word	XRBC	\ Byte count for transfer
	.word	XRLOC	\ Pointer to I/O buffer
	.byte	XRCI	\ Channel number times 2 for transfer
	.byte	XRBLKM	\ Random access block number -- msb
	.word	XRBLK	\ Random access block number -- lsb
	.word	XRTIME	\ Wait time for terminal input
	.word	XRMOD	\ Modifiers

\ File Request Queue Block

firqb	.dsect

1	.fillb		\ Reserved for returned error code
1	.fillb		\ Reserved byte
	.byte	FQJOB	\ Holds your job number times 2
	.byte	FQFUN	\ Function requested
	.val	FQERNO	\ Error message code and text begin
	.byte	FQFIL	\ Channel number times 2
	.byte	FQSIZM	\ File size in blocks -- msb
	.word	FQPPN	\ Project-programmer number
2	.blkw	FQNAM1	\ 2 word filename in radix 50
	.word	FQEXT	\ 1 word filetype in radix 50
	.word	FQSIZ	\ File size in blocks -- lsb
	.val	FQNAM2	\ 3 word new FILNAM.TYP in radix 50
	.word	FQBUFL	\ Default buffer length
	.word	FQMODE	\ MODE indicator
	.word	FQFLAG	\ Opened file's flag word as returned
	.byte	FQPFLG	\ "Protection code real" indicator
	.byte	FQPROT	\ New protection code
	.word	FQDEV	\ 2 byte ascii device name
	.byte	FQDEVN	\ 1 byte unit number
1	.fillb		\ "Unit number real" indicator
	.word	FQCLUS	\ File cluster size for file creates
	.word	FQNENT	\ Number of entries on directory lookup

\ Define some more things, these are taken from NETDEF.MAC (the DECnet/E
\ definitions file).
decimal
-21 constant	SR$LIN		\ -21  circuit control

\ Send/receive sub-function code definitions (FIRQB byte 5)

1 .dsect		\ Sub-functions of SR$LIN
	.byte	SF$ASN		\ Set line owner exe
	.byte	SF$DEA		\ Clear line owner
	.byte	SF$LON		\ Set line state to on
	.byte	SF$LOF		\ Set line state to off
	.byte	SF$LCH		\ Change line parameters

\ Network FIRQB fields we need
octal
416 constant	FQ$MFL		\ Message flags (DM)

\ FQ$MFL bits
100 .dsect
	.bit	LF.VER		\ (Point) Verification required on this circuit
	.nobit
	.nobit
	.bit	LF.RST		\ Circuit is restartable
	.bit	LF.ANS		\ (Point) Circuit is operating in answer mode
	.nobit
	.nobit
	.bit	LF.TRA		\ Trace enabled for this circuit

\ More handler indexes (used in .SPEC call)
decimal
42 constant	DDCHND		\ DDCMP device handler

\ Lifted from ODT.FTH
\ define "next" for machine code definitions
				octal
: next, 12403 , 133 , ;		decimal

\ define word in machine code.  this word is used to define other
\ words whose code is in machine language.  it is followed by the name
\ of the word to define, and the code to generate (each in the form
\ value , ) terminated by next, .

: code create smudge [compile] [ ;

code mesag .mesag , next,
code spec .spec , next,

: ?firqb firqb c@ -dup 
  if (err) type cr ."  ok" cr quit
  endif ;

2ascii TT constant TT

( unit -- )
: circ FIRQB FQBSIZ erase XRB XRBSIZ erase
  FQDEVN c!		\  unit number
  TT FQDEV !		\  device name
  -21 FQFIL c! ;	\  Circuit control

( unit -- status )
: circon
  circ
  3 FQSIZM c!		\  Circuit on
  10 FQNAM1 !		\  Originating queue limit
  30 FQNAM1 2+ !	\  Recall timer
  120 FQBUFL !		\  Hello timer
  10 FQFLAG !		\  Circuit cost
  LF.RST FQ$MFL !	\  Flags: enable restart
  7 FQCLUS !		\  Buffer quota
  mesag FIRQB c@ ;

( unit -- status )
: circoff
  circ
  4 FQSIZM c!		\  Circuit off
  mesag FIRQB c@ ;

( unit fun -- status )
: nospec
  1 fileopen no0: -dup if (err) type quit endif
  XRB XRBSIZ erase
  XRB !			\  set function code
  XRBC c!		\  set unit number
  2 XRCI c!		\  set channel number *2
  DDCHND XRCI 1+ c!	\  set handler index
  spec FIRQB c@
  1 fileclose drop ;

( unit -- status )
: ddcmp 3 nospec ;

( unit -- status )
: normal 4 nospec ;

0 variable	cclflag			\ ccl entry flag
0 variable	onflag			\ true if "on" command
0 variable	unum			\ unit number

( unit -- )
: on
  ." Turning line TT-" dup . ." on" cr
  dup ddcmp -dup if (err) type ."  - in set ddcmp mode" quit endif
  circon -dup if (err) type ."  - in set circuit on" quit endif
  ." Circuit ON successful" cr quit ;

( unit -- )
: off
  ." Turning line TT-" dup . ." off" cr
  dup circoff -dup
    if
      ." warning: " (err) type ."  - in set circuit off" cr
    endif
  normal -dup if (err) type ."  - in set normal mode" quit endif
  ." Circuit OFF successful" cr quit ;

( -- )
: action
  unum @ dup 1 < swap 127 > or if
    ." Invalid unit number, requires 1..127" cr bye
  endif
  -1 word here count 2dup upper
  2dup " ON" drop -text 0= dup onflag ! 0=
  if " OFF" drop -text 0=
    if 
      ." Usage: async unitnumber [ on | off ]" cr bye
    endif
  endif
  unum @ onflag @ if on else off endif ;

( -- )
: interact
  ." Unit number? "
  query -1 word here number drop unum !
  ." Action (on or off)? "
  query action ;
  
( -- )
: main
  fqnent @ 32767 and			\ get "line" number, ignore priv flag
  30000 = dup cclflag !			\ see if ccl entry
  if 0 corcmn c@ corcmn + 1+		\ if so point to end of core cmn
   2dup 1+ c! c!			\ put in double null terminator
   corcmn 1+ tib !			\ make that our temp input buffer
   0 in !				\ and initialize scan
   -1 word				\ get rid of the invoking ccl
   (in) c@ 0=				\ test for end of line
   if interact
   else
    -1 word here number drop unum !
    action
   endif
  else interact endif
  bye ;

