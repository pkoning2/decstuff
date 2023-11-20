#ifndef TZUTIL_H
#define TZUTIL_H
/* Routines for using TZ files */

#ifndef __GNUC__
typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef unsigned long uint32_t;
typedef short int16_t;
typedef long int32_t;
#endif

/* These are defined in arpa/inet.h but that's not included in DEC PDP11 C */
extern uint16_t ntohs (uint16_t n);
extern uint32_t ntohl (uint32_t n);

/* Note that all numbers are in network byte order (MSB first) */
struct fhdr
{
    char magic[4];              /* "TZif" */
    char version;               /* "2" or NUL */
    char reserved[15];
    int32_t tzh_ttisgmtcnt;     /* Number of UTC/Local indicators */
    int32_t tzh_ttisdstcnt;     /* Number of standard/wall indicators */
    int32_t tzh_leapcnt;        /* Number of leap seconds data items */
    int32_t tzh_timecnt;        /* Number of transition times */
    int32_t tzh_typecnt;        /* Number of local time types (ttinfo entries) */
    int32_t tzh_charcnt;        /* Number of characters of tz name */
};

struct ttinfo
{
    int32_t tt_gmtoff;
    char tt_isdst;
    unsigned char tt_abbrind;
};

/* RSTS date/time information.  The layout matches how it is found in kernel memory */
struct rstsdt
{
    unsigned short date;        /* year * 1000 + day (1 based) */
    short minutes;              /* minutes until next midnight */
    char seconds;               /* seconds until next minute */
    char ticks;                 /* ticks until next second */
};

extern const uint16_t hertz;

/* These lengths do NOT include the string terminator */
#define DATELEN	11      /* Y2K style date (4 digit year) */
#define RTIMELEN 8      /* RSTS style time */
#define RTIMELENX 14    /* RSTS style time with seconds and fraction */
#define ABBRMAX 8       /* Max length of timezone name (abbreviation) */
#define TZLEN (ABBRMAX + 9) /* Max length of timezone name/offset */

extern int32_t curt, nextt; 
extern int32_t curoff, nextoff;
extern char curabbr[], nextabbr[];
/* Buffer to receive formatted full date/time/zone */
extern char dtstr[DATELEN + 1 + RTIMELENX + 1 + TZLEN + 1];

/* Find the current timezone info for the UTC time given as argument.  On exit,
   current and next info are in global variables:
      curt =    start time of current rule
      curoff =  current offset in seconds
      curabbr = current zone name
      nextt =   start time of next rule
      nextoff = next offset
      nextabbr= next name
   If there is no next (for example, for the UTC zone), nextt is set to 2^31 - 1.
   The return value is 1 (true) if new zone data was loaded, 0 if there was no
   change from the previous call.
*/
extern int gettzinfo (int32_t now);
/* Same as gettzinfo but the argument is a local time. */
extern int getlocaltzinfo (int32_t lnow);
/* Convert the supplied local time to UTC time */
#define ltou(lnow) ((lnow) - curoff)
/* Convert the supplied UTC time to local */
#define utol(lnow) ((lnow) + curoff)
/* Convert 32 bit Unix style time (UTC seconds) into RSTS date/time */
extern void mkrststime (int32_t time, struct rstsdt *dt);
/* Convert RSTS date/time to Unix time except that it is local, not UTC */
extern int32_t lctime (const struct rstsdt *dt);
/* Convert RSTS date into US style date string */
extern void cvtdate (const struct rstsdt *dt, char *buf);
/* Convert RSTS timestamp (minutes to midnight) into am/pm style time string */
extern void cvttime (const struct rstsdt *dt, char *buf);
/* Convert RSTS timestamp (minutes to midnight) into am/pm style time string
   but with seconds and 2-digit fraction included */
extern void cvthms (const struct rstsdt *dt, char *buf);
/* Convert current zone to a string, as "name (h:mm)" with the numeric
   offset in parentheses. */
void cvttz (char *buf);
/* Convert RSTS time data to full date/time/zone in dtstr */
extern void cvtdt (const struct rstsdt *dt);

#endif /* TZUTIL_H */
