/* Routines for using TZ files */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tzutil.h"

/* Define HERTZ at compile time to use a value other than the default 60 Hz */
#ifndef HERTZ
#define HERTZ 60
#endif

/* This may also be patched (instead of overriding it at compile time) */
const uint16_t hertz = HERTZ;

#define TZFILE "NTP$:TZ.DAT"

int32_t curt = 0, nextt = 0;
int32_t curoff = (int32_t) 13 * 60 * 60, nextoff = 0;
char curabbr[ABBRMAX + 1], nextabbr[ABBRMAX + 1];
char dtstr[DATELEN + 1 + RTIMELENX + 1 + TZLEN + 1];

static FILE *tz = NULL;
static struct fhdr hdr;
static struct ttinfo info;

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
int gettzinfo (int32_t now)
{
    int i, timecnt, typecnt, charcnt;
    int32_t t;
    unsigned char curidx, nextidx;
    
    /* Just return if we already have the info */
    if (now >= curt && now < nextt) {
        return 0;
    }

    if (tz == NULL) {
        tz = fopen (TZFILE, "rb");
        if (tz == NULL) {
            perror ("open");
            exit (4);
        }
        /* Read the zone file header */
        fread (&hdr, sizeof (hdr), 1, tz);
        /* Todo: check the magic value? */
        hdr.tzh_timecnt = ntohl (hdr.tzh_timecnt);
        hdr.tzh_typecnt = ntohl (hdr.tzh_typecnt);
        hdr.tzh_charcnt = ntohl (hdr.tzh_charcnt);
    } else {
        /* Position to start of offsets vector */
        fseek (tz, sizeof (struct fhdr), SEEK_SET);
    }
    curidx = 0;
    nextidx = -1;
    curt = 0;
    nextt = 2147483647;     /* max int32_t */
    for (i = 0; i < hdr.tzh_timecnt; i++) {
        fread (&t, sizeof (t), 1, tz);
        t = ntohl (t);
        if (now <= t) {
            nextt = t;
            nextidx = i;
            break;
        }
        curt = t;
        curidx = i;
    }
    fseek (tz, sizeof (struct fhdr) + 4 * hdr.tzh_timecnt + curidx, SEEK_SET);
    fread (&curidx, 1, 1, tz);
    if (nextidx > 0) {
        fread (&nextidx, 1, 1, tz);
    }
    fseek (tz, sizeof (struct fhdr) + 5 * hdr.tzh_timecnt +
           curidx * sizeof (struct ttinfo), SEEK_SET);
    fread (&info, sizeof (struct ttinfo), 1, tz);
    curoff = ntohl (info.tt_gmtoff);
    fseek (tz, sizeof (struct fhdr) + 5 * hdr.tzh_timecnt +
           hdr.tzh_typecnt * sizeof (struct ttinfo) + info.tt_abbrind, SEEK_SET);
    fread (curabbr, sizeof (curabbr), 1, tz);
    if (i < timecnt) {
        /* There is a next */
        fseek (tz, sizeof (struct fhdr) + 5 * hdr.tzh_timecnt +
               nextidx * sizeof (struct ttinfo), SEEK_SET);
        fread (&info, sizeof (struct ttinfo), 1, tz);
        nextoff = ntohl (info.tt_gmtoff);
        fseek (tz, sizeof (struct fhdr) + 5 * hdr.tzh_timecnt +
               hdr.tzh_typecnt * sizeof (struct ttinfo) + info.tt_abbrind, SEEK_SET);
        fread (nextabbr, sizeof (nextabbr), 1, tz);
    } else {
        /* No next, supply dummy values */
        nextoff = -1;
        nextabbr[0] = '\0';
    }
    
    return 1;
}

/* Same as gettzinfo but the argument is a local time. */
int getlocaltzinfo (int32_t lnow)
{
    int32_t now;
    int ret;
    
    now = lnow - curoff;
    ret = gettzinfo (now);
    /* Check if we got the right rule.  If lnow is very close to a
       transition we may be off by one. */
    now = lnow - curoff;
    if (now < curt || now >= nextt) {
        ret = gettzinfo (now);
    }
    return ret;
}

/* Convert 32 bit Unix style time, except that it is local, into RSTS date/time */
void mkrststime (int32_t time, struct rstsdt *dt)
{
    int d, ylen;
    unsigned int y;
    int32_t t;

    time = utol (time);     /* UTC to local seconds */
    d = time / 86400;
    t = time % 86400;
    dt->minutes = 1440 - t / 60;
    dt->seconds = 60 - t % 60;
    dt->ticks = hertz;      /* Default to exact second */
    /* the easiest way to get year and day-in-year is with a loop */
    y = 0;
    for (;;) {
        ylen = 365 + ((y & 3) == 2);
        if (d < ylen) {
            break;
        }
        d -= ylen;
        y++;
    }
    dt->date = (y * 1000) + d + 1;
}

/* Convert RSTS date/time to Unix time except that it is local, not UTC */
int32_t lctime (const struct rstsdt *dt)
{
    unsigned short date;
    int y, d;
    
    date = dt->date - 1;
    y = date / 1000;
    d = date % 1000;
    d += y * 365 + ((y + 1) >> 2);
    return (uint32_t) d * 86400 + (uint32_t) (1440 - dt->minutes) * 60 + (60 - dt->seconds);
}

/* Modified from FLX 2.6 */
static const char months[12][4] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
static int days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};

/* Convert RSTS date into US style date string */
void cvtdate (const struct rstsdt *dt, char *buf)
{
    uint16_t date = dt->date;
    long day, yr;
    int mon;

    if (date == 0) {            /* no date present */
        strcpy (buf, "   none");
        return;
    }       
    yr = (long) date / 1000 + 1970;
    day = date % 1000;
    if (yr & 3) {
        days[1] = 28;
    } else {
        days[1] = 29;
    }
    for (mon = 0; mon < 12; mon++) {
        if (day <= days[mon]) {
            break;
        }
        day -= days[mon];
    }
    sprintf (buf, "%2ld-%3s-%04ld", day, months[mon], yr);
}

/* Convert RSTS timestamp (minutes to midnight) into am/pm style time string */
void cvttime (const struct rstsdt *dt, char *buf)
{
    uint16_t time = dt->minutes;
    int hour, min;
    char m;

    if (time == 0) {            /* no time present */
        strcpy (buf, "  none");
        return;
    }       
    time = 1440 - time;         /* now time since midnight */
    hour = time / 60;
    min = time % 60;
    if (hour >= 12) {
        hour -= 12;
        m = 'p';
    } else {
        m = 'a';
    }
    if (hour == 0) {
        hour = 12;
    }
    sprintf (buf, "%2d:%02d %1cm", hour, min, m);
}

/* Convert RSTS timestamp (minutes to midnight) into am/pm style time string
   but with seconds and 2-digit fraction included */
void cvthms (const struct rstsdt *dt, char *buf)
{
    uint16_t time = dt->minutes;
    int hour, min, sec, ticks = dt->ticks;
    char m;

    if (time == 0) {            /* no time present */
        strcpy (buf, "     none");
        return;
    }       
    time = 1440 - time;         /* now time since midnight */
    hour = time / 60;
    min = time % 60;
    if (hour >= 12) {
        hour -= 12;
        m = 'p';
    } else {
        m = 'a';
    }
    if (hour == 0) {
        hour = 12;
    }
    sec = 60 - dt->seconds;
    if (ticks != 0) {
        ticks = hertz - ticks;
    }
    /* convert to centiseconds, properly rounded */
    ticks = (ticks * 100 + hertz / 2) / hertz;
    sprintf (buf, "%2d:%02d:%02d.%02d %1cm", hour, min, sec, ticks,  m);
}

/* Convert current zone to a string, as "name (h:mm)" with the numeric
   offset in parentheses. */
void cvttz (char *buf)
{
    int hm = curoff / 60;

    sprintf (buf, "%s (%d:%02d)", curabbr, hm / 60, hm % 60);
}

/* Convert RSTS time data to full date, time, and zone string */
void cvtdt (const struct rstsdt *dt)
{
    cvtdate (dt, dtstr);
    dtstr[DATELEN] = ' ';
    cvthms (dt, dtstr + DATELEN + 1);
    dtstr[DATELEN + 1 + RTIMELENX] = ' ';
    cvttz (dtstr + DATELEN + 1 + RTIMELENX + 1);
}
