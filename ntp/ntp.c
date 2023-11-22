/* NTP for RSTS/E */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rstsys.h"
#include "tzutil.h"

#define NOSUCH  5       /* Ethernet driver error code for "no packets pending" */
#define DATERR  13      /* Some Ethernet packets were lost */
#define MAGRLE  40      /* Oversized Ethernet packet */
#define UU_DAT  -14     /* Date/Time changer */
#define UU_DET  7       /* Detach */
#define JFLOCK  040000  /* Lock in memory flag */
#define JFSPRI  000400  /* Special (half step) priority boost */

#define DATE    01000   /* Kernel address of date/time */
#define LOWAPR  7       /* APR to use for mapping date/time in kernel lowcore */
#define LOWLEN  1       /* Length in slivers */
#define LOWPAGE (DATE >> 6) /* Sliver PA of lowcore */
#define KDATE   (LOWAPR << 13)

struct ethhdr 
{
    uint8_t dest[6];
    uint8_t src[6];
    uint16_t proto;
};

#define ETH_IP 0x0008   /* 08-00, as a little endian integer */
struct iphdr            /* without options */
{
    uint8_t verlen;
    uint8_t tos;
    uint16_t tl;
    uint16_t id;
    uint16_t fragoff;
    uint8_t ttl;
    uint8_t proto;
    uint16_t hcs;
    uint8_t src[4];
    uint8_t dst[4];
};

#define IP_UDP 17   /* IP proto for UDP */
struct udphdr
{
    uint16_t src;
    uint16_t dest;
    uint16_t len;
    uint16_t cksum;
};

/* Offset from NTP base to Unix base (1-Jan-70) which conveniently is
 * also the RSTS base */
#define UNIXBASE 2208988800UL

/* NTP port number */
#define NTPPORT (123 << 8)  /* port 123, in network byte order */
#define NTPVERSION 4

struct ntpshort
{
    uint32_t seconds;
    uint32_t fraction;
};

/* The fixed parts of the NTP packet, not including the extension fields */
struct ntphdr
{
    uint8_t mode;       /* LI, VN, mode */
    uint8_t stratum;
    uint8_t poll;
    uint8_t precision;
    uint32_t root_delay;
    uint32_t root_disp;
    char refid[4];
    struct ntpshort ref_ts;
    struct ntpshort origin_ts;
    struct ntpshort rec_ts;
    struct ntpshort xmit_ts;
};

static void check (const char *msg)
{
    int err = RSTS$FIRQB->firqb;
    if (err != 0) {
        printf ("%s: error %d: ", msg, err);
        RSTS$CLRFQB ();
        RSTS$FIRQB->fqfun = RSTS$FIP$ERRFQ;
        RSTS$FIRQB->fqfil = err;
        RSTS$CALFIP ();
        printf ("%28s\n", &(RSTS$FIRQB->fqfil));
        exit (2);
    }
}

static void setxrb (void *buf, int size)
{
    register XRB * const xrb = RSTS$XRB;

    RSTS$CLRXRB ();
    xrb->xrlen = size;
    xrb->xrloc = (short int) buf;
}

#define ETH_CH (4 * 2)
/* Number of receive buffers.  NTP doesn't need so many (one would do)
 * but this allows us to deal with a burst of other IP broadcast
 * messages for other services, without incurring receiver overrun. */
#define ETH_BUFS 5
/* Logical name for Ethernet interface to use */
#define NTPIF "NTP$IF:"

/* OPEN the Ethernet device NTP$IF: */
static void openeth (int ch2)
{
    register FIRQB * const fqb = RSTS$FIRQB;

    /* Scan the name (logical name) to a FIRQB device spec */
    RSTS$CLRFQB ();
    setxrb (NTPIF, sizeof (NTPIF) - 1);
    /* Set byte count also */
    RSTS$XRB->xrbc = sizeof (NTPIF) - 1;
    RSTS$FSS ();
    check ("fss");
    fqb->fqfil = ch2;
    fqb->fqmode = 0x8000 + 128;     /* No DEC style length */
    fqb->fqclus = ETH_BUFS;         /* Receive buffers for this portal */
    fqb->fqnent = ETH_IP;           /* Ethertype 08-00 */
    fqb->fqfun = RSTS$FIP$OPNFQ;
    RSTS$CALFIP ();
    check ("ethernet open");
}

/* Close the Ethernet portal */
static void closeeth (int ch2)
{
    register FIRQB * const fqb = RSTS$FIRQB;
    
    RSTS$CLRFQB ();
    fqb->fqfil = ch2;
    fqb->fqfun = RSTS$FIP$CLSFQ;
    RSTS$CALFIP ();
    check ("ethernet close");
}

static const uint8_t bc[6] = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff };
#define ethhnd 050

/* Enable broadcast on the Ethernet portal */
static void setbc (int ch2)
{
    register XRB * const xrb = RSTS$XRB;

    RSTS$CLRXRB ();
    xrb->xrci = ch2;
    xrb->xrlen = -3;        /* function code: set multicast */
    xrb->xrbc = sizeof (bc);
    xrb->xrloc = (short) &bc;
    xrb->xrblkm = ethhnd;   /* Device handler index for Ethernet */
    RSTS$SPEC ();
    check ("enable broadcast");
}

/* Receive an NTP packet, if one is pending.  Returns a pointer to the
   NTP header if so, NULL if no NTP packet is currently waiting.  We
   will loop through all pending packets (in case there are broadcasts
   that aren't NTP) but return if there are no more packets, or if an
   NTP packet is received even if additional ones are pending. */
static void * getntppkt (int ch2, void *buf, int len)
{
    register XRB * const xrb = RSTS$XRB;
    register struct ethhdr * const eth = buf;
    register struct iphdr * const ip = (struct iphdr * const)((char *) buf + sizeof (struct ethhdr));
    register struct udphdr * const udp = (struct udphdr * const) ((char *) buf + sizeof (struct ethhdr) + sizeof (struct iphdr));
    
    for (;;) {
        setxrb (buf, len);
        xrb->xrci = ch2;
        RSTS$READ ();
        /* Some errors are ignored: no packet pending, packets lost, oversized packet */
        if (RSTS$FIRQB->firqb == NOSUCH ||
            RSTS$FIRQB->firqb == DATERR ||
            RSTS$FIRQB->firqb == MAGRLE) {
            /* Report no packet */
            return NULL;
        }
        check ("ethernet receive");
        if (eth->proto != ETH_IP) {
            continue;           /* should not happen, driver should filter */
        }
        if (ip->proto != IP_UDP) {
            continue;
        }
        if (udp->dest != NTPPORT) {
            continue;
        }
        /* NTP packet, return with its start address in the buffer */
        return udp + 1;
    }
}

static char buf[600];
#define announcebuf (buf + 100)
static int pktlen;

static struct rstsdt rnow;

/* Copy the current date/time from the kernel into "rnow".  The kernel
   doesn't offer a race-free way to get it (.DATE doesn't block
   interrupts) so instead keep reading until we get the same answer
   twice. */
static void updrnow (void)
{
    register const struct rstsdt * const kdt = (const struct rstsdt * const) KDATE;

    for (;;) {
        rnow.ticks = kdt->ticks;
        rnow.seconds = kdt->seconds;
        rnow.minutes = kdt->minutes;
        rnow.date = kdt->date;
        if (rnow.ticks == kdt->ticks && rnow.seconds == kdt->seconds) {
            return;
        }
    }
}

/* Set the supplied date/time into the kernel.  We don't block
   interrupts, so start by setting the ticks to next second to a full
   second, then write the date/time. */
static void updkdate (const struct rstsdt *dt)
{
    register struct rstsdt * const kdt = (struct rstsdt * const) KDATE;

    kdt->ticks = hertz;     /* Prevent rollover in the middle of settings things */
    kdt->date = dt->date;
    kdt->minutes = dt->minutes;
    kdt->seconds = dt->seconds;
    kdt->ticks = dt->ticks; /* Finish by setting the real tick count */
}

static char omsbuf[255];
/* Send notification to OMS, if active. */
static void sendoms (const char *msg)
{
    register FIRQB * const fqb = RSTS$FIRQB;
    register XRB * const xrb = RSTS$XRB;
    int l = strlen (msg);
    char *p = omsbuf;
    
    /* Build the OMS message buffer */
    *p++ = 3;       /* Reply flag: noreply */
    *p++ = 0;
    *p++ = 4;       /* Facility: NTP */
    *p++ = 3;
    strcpy (p, "NTP");
    p += 4;         /* 3 bytes for string length plus one more for word alignment (!) */
    *p++ = 1;       /* Text */
    if (l >= sizeof (omsbuf) - (p - omsbuf)) {
        puts ("Message too long");
        return;
    }
    *p++ = l;
    strcpy (p, msg);
    p += l;
    /* Compute the data length in omsbuf */
    l = p - omsbuf;
    if ((l & 1) != 0) {
        l++;                    /* Round up length to even */
    }
    RSTS$CLRFQB ();
    RSTS$CLRXRB ();
    fqb->fqfil = -11;           /* "local send with privileges" */
    fqb->fqsizm = 0213;         /* Local object 11 */
    fqb->fqflag = 2;            /* OMS function code for "request" */
    strcpy ((char *) (&fqb->fqpflg), "NTP");    /* Facility name */
    xrb->xrlen = l;
    xrb->xrbc = l;
    xrb->xrloc = (uint16_t) omsbuf;
    RSTS$MESAG ();
    /* "No such receiver" is silently ignored */
    if (fqb->firqb == NOSUCH) {
        return;
    }
    check ("OMS send");
}

/* One-time initialization */
static void init (void)
{
    int32_t nowsec;
    register FIRQB * const fqb = RSTS$FIRQB;
    uint16_t lowwindowid;
    
    /* First map kernel memory so we can read/write the date/time values */
    RSTS$CLRFQB ();
    fqb->fqfil = 4;         /* Create window */
    fqb->fqppn = LOWAPR << 8; /* Base APR of window in upper byte */
    ((uint16_t *) &(fqb->fqnam1))[1] = LOWLEN;
    fqb->fqmode = 2;        /* Read/write access */
    RSTS$PLAS ();
    check ("Create lowcore window");
    lowwindowid = fqb->fqppn & 0377;
    RSTS$CLRFQB ();
    fqb->fqfil = 8;         /* Map window */
    fqb->fqsiz = LOWPAGE;   /* Physical address to map */
    fqb->fqppn = lowwindowid;
    fqb->fqext = -4;        /* Special region ID value for "physical memory" */
    fqb->fqbufl = LOWLEN;   /* Length to map */
    fqb->fqmode = 2;        /* Read/write access */
    RSTS$PLAS ();
    check ("Map lowcore window");
    /* Set priority boost and lock in memory */
    RSTS$CLRFQB ();
    RSTS$CLRXRB ();
    RSTS$XRB->xrlen = JFLOCK | JFSPRI;
    RSTS$SET ();
    check ("Set flags");
    /* Go get current date/time */
    updrnow ();
    /* Convert RSTS date/time to Unix style seconds since epoch, but local */
    nowsec = lctime (&rnow);
    /* Obtain the timezone information matching the current local time */
    getlocaltzinfo (nowsec);
    /* Now open the Ethernet */
    openeth (ETH_CH);
    setbc (ETH_CH);
}

static void mainloop ()
{
    int32_t nowsec, cursec;
    uint32_t nowfrac16;
    struct ntphdr * ntp;
    int32_t delay = 20;
    struct rstsdt dt;
    int ticks;
    int announce;

    for (;;) {
        /* What is the local time as we know it at the moment? */
        updrnow ();
        /* Get UTC seconds */
        cursec = ltou (lctime (&rnow));
        delay = nextt - cursec;
        if (delay > 32767) {
            delay = 32767;
        }
        /* Conditionally sleep until next offset change or "forever" */
        RSTS$CLRXRB ();
        RSTS$XRB->xrlen = 01000000 | delay;
        RSTS$SLEEP ();
        /* Try to receive something */
        ntp = getntppkt (ETH_CH, buf, sizeof (buf));
        if (ntp) {
            /* We received an NTP packet, process it */
            nowsec = ntohl (ntp->xmit_ts.seconds) - UNIXBASE;
            /* Keep the 16 MSB of the fractional time, that's plenty */
            nowfrac16 = ntohs ((uint16_t) (ntp->xmit_ts.fraction));
            /* Assume we'll announce if this is a change in offset */
            announce = gettzinfo (nowsec);
            /* Convert to RSTS format.  First compute ticks, rounded. */
            ticks = hertz - ((nowfrac16 * hertz + 32768UL) >> 16);
            if (ticks == 0) {
                /* It rounded up to a whole second, so set it to 0 and
                   advance the time in seconds by one. */
                ticks = hertz;
                nowsec++;
            }
            mkrststime (nowsec, &dt);
            dt.ticks = ticks;
            /* What is the local time now (before update? */
            updrnow ();
            /* Get UTC seconds */
            cursec = ltou (lctime (&rnow));
            /* Now write the updated date/time to the kernel */
            updkdate (&dt);
            /* See if we should announce this.  Compute the delta time */
            cursec -= nowsec;
            if (cursec < -1 || cursec > 1) {
                /* Changing more than one second, announce it */
                announce = 1;
            }
            if (announce) {
                /* "announce" means two things:
                   1. Wake up any sleeping jobs.
                   2. Send a message to OMS saying the time was updated.
                */
                RSTS$CLRFQB ();
                RSTS$FIRQB->fqfun = UU_DAT;
                /* Do a no-change date/time "change", that still does a wakeup */
                RSTS$UUO ();
                /* Send to OMS. */
                cvtdt (&dt);
                sprintf (announcebuf, "Time updated to %s, stratum %d, source %s",
                         dtstr, ntp->stratum, ntp->refid);
                /* This doesn't seem to be working... */
                sendoms (announcebuf);
            }
        } else {
            /* TODO check for offset change */
        }
    }
    closeeth (ETH_CH);
}

int main (int argc, char **argv)
{
    init ();
    cvtdt (&rnow);
    printf ("NTP started %s\n", dtstr);
    /* Detach */
    RSTS$CLRFQB ();
    RSTS$FIRQB->fqfun = UU_DET;
    RSTS$FIRQB->fqfil = 0200;       /* Close terminal, detach self */
    RSTS$UUO ();
    check ("detach");

    mainloop ();

    puts ("Exiting NTP");
    return 1;   /* success */
}

    
