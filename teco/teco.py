#!/usr/bin/env python3

"""TECO for Python

Copyright (C) 2006, 2014 by Paul Koning

This is an implementation of DEC Standard TECO in Python.
It corresponds to PDP-11/VAX TECO V40, give or take a few details
that don't really carry over.
"""

import os
import sys
import re
import time
import traceback
import glob
import warnings
import copy
import atexit
import threading
import tempfile

try:
    import curses
    curses.initscr ()
    curses.endwin ()
    curses.def_shell_mode ()
    cursespresent = True
except ImportError:
    cursespresent = False
    
try:
    import wx
    wxpresent = True
except ImportError:
    wxpresent = False
    
# char codes
null  = '\000'
ctrlc = '\003'
ctrle = '\005'
bs    = '\010'
bell  = '\007'
tab   = '\011'
lf    = '\012'
vt    = '\013'
ff    = '\014'
cr    = '\015'
crlf  = cr + lf
ctrls = '\023'
ctrlu = '\025'
ctrlx = '\030'
esc   = '\033'
rub   = '\177'
eol   =  lf + vt + ff          # all these are TECO end of line (TODO)

# global variables
screen = None
display = None
dsem = None
exiting = False

# Other useful constants
VERSION = 40

# There is no good match for the CPU and OS types.  Based on the
# features, PDP-11 makes sense, since this TECO looks like TECO-11.
# The implementation of ^B says we'd like to call it RSX/VMS, but
# that won't work because various code (like TECO.TEC) will use that
# as a hint to construct filenames with RMS format switches in them,
# and those look like Unix directory names, so all hell will break
# loose.  The best answer, therefore, is to call it RT-11, which
# has neither directories nor file version numbers nor filename
# switches.  RSX/VMS has all of those, and RSTS/E has all except
# versions -- but any of those would give Unix filename handlers
# conniption fits...
CPU     = 0                    # Pretend to be a PDP-11, that's closest
OS      = 7                    # OS is Unix, but pretend it's RT-11

# unbuffered input: Python Cookbook V2 section 2.23
try:
    from msvcrt import getch
    rubchr = '\010'
except ImportError:
    rubchr = '\177'
    def getch ():
        """Get a character in raw (unechoed, single character) mode.
        """
        import tty, termios
        fd = sys.stdin.fileno ()
        old_settings = termios.tcgetattr (fd)
        try:
            tty.setraw (fd)
            ch = sys.stdin.read (1)
        finally:
            termios.tcsetattr (fd, termios.TCSADRAIN, old_settings)
        return ch

# Enhanced traceback, from Python Cookbook section 8.6, slightly tweaked
maxstrlen = 200
def print_exc_plus ():
    '''Print all the usual traceback information, followed by a listing of
    all the local variables in each frame.

    Variable values are truncated to 200 characters max for readability,
    and converted to printable characters in standard TECO fashion.
    '''
    tb = sys.exc_info ()[2]
    while tb.tb_next:
        tb = tb.tb_next
    stack = [ ]
    f = tb.tb_frame
    while f:
        stack.append (f)
        f = f.f_back
    stack.reverse ()
    endwin ()
    traceback.print_exc ()
    print("Locals by frame, innermost last")
    if stack[0].f_code.co_name == "?":
        del stack[0]
    for frame in stack:
        print()
        print("Frame %s in %s at line %s" % (frame.f_code.co_name,
                                             frame.f_code.co_filename,
                                             frame.f_lineno))
        for key, value in list(frame.f_locals.items ()):
            print("\t%20s = " % key, end=' ')
            try:
                value = printable (str (value))
                if len (value) > maxstrlen:
                    value = value[:maxstrlen] + "..."
                print(value)
            except:
                print("<ERROR while printing value>")
                
# Transform a generic binary string to a printable one.  Try to
# optimize this because sometimes it is fed big strings.
# tab through cr are printed as is; other control chars are uparrowed
# except for esc of course.
# Taken from Python Cookbook, section 1.18
_printre = re.compile ("[\000-\007\016-\037\177]")
_printdict = { }
for c in range (0o40):
    _printdict[chr (c)] = '^' + chr (c + 64)
_printdict[esc] = '$'
_printdict[rub] = "^?"

def _makeprintable (m):
    return _printdict[m.group (0)]

def printable(s):
    """Convert the supplied string to a printable string,
    by converting all unusual control characters to uparrow
    form, and escape to $ sign.
    """
    return _printre.sub (_makeprintable, s)

# Error handling
class err (Exception):
    '''Base class for TECO errors.
    
    Specific errors are derived from this class; the class name is
    the three-letter code for the error, and the class doc string
    is the event message string.
    '''
    def __init__ (self, teco, *a):
        self.teco = teco
        self.args = tuple (printable (arg) for arg in a)
        teco.clearargs ()
        
    def show (self):
        endwin ()
        detail = self.teco.eh & 3
        if detail == 1:
            print("?%s" % self.__class__.__name__)
        else:
            if self.args:
                msg = self.__class__.__doc__ % self.args
            else:
                msg = self.__class__.__doc__
            print("?%s   %s" % (self.__class__.__name__, msg))
        if self.teco.eh & 4:
            print(printable (self.teco.failedcommand ()), "?")

class ARG (err): 'Improper Arguments'
class BNI (err): '> not in iteration'
class FER (err): 'File Error'
class FNF (err): 'File not found "%s"'
class ICE (err): 'Illegal ^E Command in Search Argument'
class IEC (err): 'Illegal character "%s" after E'
class IFC (err): 'Illegal character "%s" after F'
class IFN (err): 'Illegal character "%s" in filename'
class IIA (err): 'Illegal insert arg'
class ILL (err): 'Illegal command "%s"'
class ILN (err): 'Illegal number'
class INP (err): 'Input error'
class IPA (err): 'Negative or 0 argument to P'
class IQC (err): 'Illegal " character'
class IQN (err): 'Illegal Q-register name "%s"'
class IRA (err): 'Illegal radix argument to ^R'
class ISA (err): 'Illegal search arg'
class ISS (err): 'Illegal search string'
class IUC (err): 'Illegal character "%s" following ^'
class MAP (err): "Missing '"
class MLA (err): 'Missing Left Angle Bracket'
class MLP (err): 'Missing ('
class MRA (err): 'Missing Right Angle Bracket'
class MRP (err): 'Missing )'
class NAB (err): 'No arg before ^_'
class NAC (err): 'No arg before ,'
class NAE (err): 'No arg before ='
class NAP (err): 'No arg before )'
class NAQ (err): 'No arg before "'
class NAS (err): 'No arg before ;'
class NAU (err): 'No arg before U'
class NCA (err): 'Negative argument to ,'
class NFI (err): 'No file for input'
class NFO (err): 'No file for output'
class NPA (err): 'Negative or 0 argument to P'
class NYA (err): 'Numeric argument with Y'
class NYI (err): 'Not Yet Implemented'
class OFO (err): 'Output file already open'
class OUT (err): 'Output error'
class PES (err): 'Attempt to Pop Empty Stack'
class POP (err): 'Attempt to move Pointer Off Page with "%s"'
class SNI (err): '; not in iteration'
class SRH (err): 'Search failure "%s"'
class TAG (err): 'Missing Tag !%s!'
class UTC (err): 'Unterminated command "%s"'
class UTM (err): 'Unterminated macro'
class XAB (err): 'Execution aborted'
class YCA (err): 'Y command aborted'

# Other exceptions used for misc purposes
class ExitLevel (Exception): pass
class ExitExecution (Exception): pass

# text reformatting for screen display
tabre = re.compile (tab)
_tabadjust = 0
def _untabify (m):
    global _curcol, _tabadjust
    pos = m.start () + _tabadjust
    count = 8 - (pos & 7)
    if _curcol > pos:
        _curcol += count - 1
    _tabadjust += count - 1
    return " " * count

def untabify (line, curpos, width):
    """Convert tabs to spaces, and wrap the line as needed into chunks
    of the specified width.  Returns the list of chunks, and the row
    and column corresponding to the supplied curpos.  There is always
    at least one chunk, which may have an empty string if the supplied
    line was empty.

    Each chunk is a pair of text and wrap flag.  Wrap flag is True
    if this chunk of text is wrapped, i.e., it does not end with a
    carriage return, and False if it is the end of the line.
    
    Note that a trailing cr and/or lf is stripped from the input line.
    """
    global _curcol, _tabadjust
    _curcol = curpos
    _tabadjust = 0
    line = tabre.sub (_untabify, printable (line.rstrip (crlf)))
    currow = 0
    if True:            # todo: truncate vs. wrap mode
        lines = [ ]
        while len (line) > width:
            lines.append ((line[:width], True))
            line = line[width:]
            if _curcol > width:
                currow += 1
                _curcol -= width
        lines.append ((line, False))
    return lines, currow, _curcol
    
# Property makers
def commonprop (name, doc=None):
    """Define a property that references an attribute of 'teco'
    (the common state object for TECO).
    """
    def _fget (obj):
        return getattr (obj.teco, name)
    def _fset (obj, val):
        return setattr (obj.teco, name, val)
    _fget.__name__ = "get_%s" % name
    _fset.__name__ = "set_%s" % name
    return property (_fget, _fset, doc=doc)

def bufprop (name, doc=None):
    """Define a property that references an attribute of 'buffer'
    (the text buffer object for TECO).
    """
    def _fget (obj):
        return getattr (obj.buffer, name)
    def _fset (obj, val):
        return setattr (obj.buffer, name, val)
    _fget.__name__ = "get_%s" % name
    _fset.__name__ = "set_%s" % name
    return property (_fget, _fset, doc=doc)

# Global state handling
class teco (object):
    '''This class defines the global state for TECO, i.e., the state
    that is independent of the macro level.  It also points to state
    that is kept in separate classes, such as the buffer, the command
    input, and the command level for the interactive level.
    '''
    def __init__(self):
        self.radix = 10
        self.ed = 0
        self.eh = 0
        self.es = 0
        if wxpresent:
            self.etfixed = 1024     # Display available
        elif cursespresent:
            self.etfixed = 512      # text terminal "watch" available
        else:
            self.etfixed = 0        # neither available
        self.et = 128 + self.etfixed
        self.eu = -1
        self.ev = 0
        setattr (self, ctrlx, 0)    # ^X flag
        self.trace = False
        self.laststringlen = 0
        self.qregs = { }
        self.lastsearch = ""
        self.lastfilename = ""
        self.qstack = [ ]
        self.clearargs ()
        self.interactive = command_level (self)
        self.buffer = buffer (self)
        self.cmdhandler = command_handler (self)
        self.screenok = False
        self.incurses = False
        self.watchparams = [ 8, 80, 24, 0, 0, 0, 0, 0 ]
        self.curline = 16
        
    buf = bufprop ("text")
    dot = bufprop ("dot")
    end = bufprop ("end")
    
    def doop (self, c):
        """Process a pending arithmetic operation, if any.
        self.arg is left with the current term value.
        """
        if self.op:
            if self.op in '+-' and self.arg is None:
                self.arg = 0
            if self.num is None:
                raise ILL (self, c)
            if self.op == '+':
                self.arg += self.num
            elif self.op == '-':
                self.arg -= self.num
            elif self.op == '*':
                self.arg *= self.num
            elif self.op == '/':
                if not self.num:
                    raise ILL (self, '/')
                self.arg //= self.num
            elif self.op == '&':
                self.arg &= self.num
            elif self.op == '#':
                self.arg |= self.num
        else:
            self.arg = self.num
        
    def getterm (self, c):
        """Get the current term, i.e., the innermost expression
        part in parentheses.
        """
        self.doop (c)
        ret = self.arg
        self.num = None
        self.op = None
        self.arg = None
        return ret

    def leftparen (self):
        """Proces a left parenthesis command, by pushing the current
        partial expression state onto the operation stack.
        """
        self.opstack.append ((self.arg, self.op))
        self.arg = None
        self.op = None

    def rightparen (self):
        """Process a right parenthesis command, by setting the current
        right-hand side to the expression term value, and popping the
        operation stack state for the left hand and operation (if any).
        """
        if self.opstack:
            try:
                self.num = self.getterm (')')
            except err:
                raise NAP (self)
            self.arg, self.op = self.opstack.pop ()
        else:
            raise MLP (self)

    def operator (self, c):
        """Process an arithmetic operation character.
        """
        if self.num is None:
            if c in "+-" and self.arg is None:
                self.op = c
                return
            else:
                raise ILL (self, c)
        self.doop (c)
        self.num = None
        self.op = c

    def digit (self, c):
        """Process a decimal digit.  8 and 9 generate an error if
        the current radix is octal.
        """
        if self.num is None:
            self.num = 0
        n = int (c)
        if n >= self.radix:
            raise ILN (self)
        self.num = self.num * self.radix + n

    def getarg (self, c):
        """Get a complete argument, or None if there isn't one.
        If there are left parentheses that have not yet been matched,
        that is an error.  + or - alone are taken to be +1 and -1
        respectively.
        """
        if self.opstack:
            raise MRP (self)
        if self.op and self.op in '+-' and self.num is None and self.arg is None:
            self.num = 1
        return self.getterm (c)

    def getoptarg (self, c):
        """Get an optional argument.  Unlike getarg, this is legal
        while we're in an incomplete expression.  This method is used
        for commands that do something if given an argument, but return
        a value if not.  This way, the second case can be used as
        an element of an expression.
        """
        if self.op and self.op in '+-' and self.num is None and self.arg is None:
            self.num = 1
        if self.num is None:
            return None
        return self.getarg (c)
    
    def setval (self, val):
        """Set the command result value into the expression state.
        """
        self.num = val
        self.clearmods ()

    def bitflag (self, name):
        """Process a bit-flag type command, i.e., one that is read by
        supplying no argument, set by supplying one, and has its bits
        fiddled by two arguments.
        """
        n = self.getoptarg (name)
        if n is None:
            self.setval (getattr (self, name))
        else:
            if self.arg2 is not None:
                n = (getattr (self, name) | n) & (~self.arg2)
            if n & 32768:
                # Sign extend upper 16 bits
                n |= -32768
            fixed = getattr (self, name + "fixed", 0)
            self.clearargs ()
            setattr (self, name, n | fixed)
    
    def numflag (self, name):
        """Process a numeric flag type command, i.e., one that is
        read by supplying no argument, and set by supplying the new value.
        """
        n = self.getoptarg (name)
        if n is None:
            self.setval (getattr (self, name))
        else:
            self.clearargs ()
            setattr (self, name, n)
    
    def lineargs(self, c):
        """Process the argument(s) for a command that references lines.
        If one argument is present, that is taken as a line count
        displacement from dot.  If two arguments are present, that is
        the start and end of the the range.
        """
        m, n = self.arg2, self.getarg (c)
        if n is None:
            n = 1
        if m is None:
            if n > 0:
                m, n = self.dot, self.buffer.line (n)
            else:
                m, n = self.buffer.line (n), self.dot
        else:
            if m < 0 or n > self.end or m > n:
                raise POP (self, c)
        return (m, n)

    def clearmods (self):
        """Clear modifier flags (colon and at sign).
        """
        self.colons = 0
        self.atmod = False

    def clearargs (self):
        """Reinitialize all expression state, as well as modifiers.
        """
        self.opstack = [ ]
        self.arg = None
        self.arg2 = None
        self.num = None
        self.op = None
        self.clearmods ()

    def failedcommand (self):
        """Return the last failed interactive command, i.e., the last
        command up to the point where execution was aborted.
        """
        return self.interactive.failedcommand ()

    def lastcommand (self):
        """Return the last interactive command, in full.
        """
        return self.interactive.lastcommand ()
        
    def mainloop (self):
        """This is the TECO command loop.  It fetches the command string,
        handles special immediate action forms, and otherwise executes
        the command as supplied.  Errors are handled by catching the
        TECO error exception, and printing the error information as
        controlled by the EH flag.
        """
        preverror = False
        try:
            while True:
                if not self.cmdhandler.eifile:
                    if screen:
                        y, x = screen.getmaxyx ()
                        screen.untouchwin ()
                        screen.move (y - 1, 0)
                        screen.clrtoeol ()
                        screen.refresh ()
                        curses.reset_shell_mode ()
                        self.incurses = False
                        self.screenok = False
                    self.updatedisplay ()
                    # clear "in startup mode" flag
                    self.et &= ~128
                    self.autoverify (self.ev)
                    sys.stdout.write ("*")
                sys.stdout.flush ()
                cmdline = self.cmdhandler.teco_cmdstring ()
                self.clearargs ()
                if cmdline and cmdline[-1] != esc:
                    # it was an immediate action command -- handle that
                    cmd = cmdline[0]
                    if cmd == '*':
                        try:
                            q = self.interactive.qreg (cmdline[1])
                        except err as e:
                            e.show ()
                        else:
                            q.setstr (self.lastcommand ())
                        continue
                    elif cmd == '?':
                        if preverror:
                            print(printable (self.failedcommand ()))
                        continue
                    elif cmd == lf:
                        cmdline = "lt"
                    else:
                        cmdline = "-lt"
                try:
                    preverror = False
                    self.runcommand (cmdline)
                except ExitExecution:
                    pass
                except SystemExit:
                    endwin ()
                    enddisplay ()
                    break
                except err as e:
                    preverror = True
                    e.show ()
                    ###print_exc_plus ()             # *** for debug
                    # Turn off any EI
                    self.cmdhandler.ei ("")
                except:
                    print_exc_plus ()
        except:
            print_exc_plus ()

    def runcommand (self, s):
        """Execute the specified TECO command string as an interactive
        level command.
        """
        self.interactive.run (s)

    def screentext (self, height, width, curlinenum):
        """Given a screen height and width in characters, and the
        line on which we want 'dot' to appear, determine the text that
        fits on the screen.

        Returns a three-element tuple: lines, row, and column corresponding
        to dot.

        Lines is a list; each list element is a pair of text and
        wrap flag.  Wrap flag is True if this chunk of text is wrapped,
        i.e., it does not end with a carriage return, and False if
        it is the end of the line.
        """
        curlinestart = self.buffer.line (0)
        curcol = self.dot - curlinestart
        line = self.buf[curlinestart:self.buffer.line(1)]
        lines, currow, curcol = untabify (line, curcol, width)
        n = 1
        # First add on lines after the current line, up to the
        # window height, if we have that many
        while len (lines) < height:
            start, end = self.buffer.line (n), self.buffer.line (n + 1)
            if start >= self.end:
                break
            line, i, i = untabify (self.buf[start:end], 0, width)
            lines += line
            n += 1
        # Next, add lines before the current line, until we have
        # enough to put the cursor onto the line where we want it,
        # but also try to fill the screen
        n = 0
        while currow < curlinenum or len (lines) < height:
            start, end = self.buffer.line (-n - 1), self.buffer.line (-n)
            if not end:
                break
            line, i, i = untabify (self.buf[start:end], 0, width)
            lines = line + lines
            currow += len (line)
            n += 1
        # Now trim things, since (a) the topmost line may have wrapped
        # so the cursor may be lower than we want it to be, and (b)
        # we now probably have more lines than we want at the end
        # of the screen.
        trim = min (currow - curlinenum, len (lines) - height)
        if trim > 0:
            lines = lines[trim:]
            currow -= trim
        if len (lines) > height:
            lines = lines[:height]
        return lines, currow, curcol
    
    def enable_curses (self):
        """Enable curses (VT100 style screen watch) mode, if available
        in this Python installation.  This is a NOP if curses is not
        available.
        """
        global screen
        if not cursespresent:
            return
        if not screen:
            atexit.register (endwin)
            screen = curses.initscr ()
            curses.noecho ()
            curses.nonl ()
            curses.raw ()
            curses.def_prog_mode ()
        else:
            curses.reset_prog_mode ()
        self.incurses = True
        self.watchparams[2], self.watchparams[1] = screen.getmaxyx ()
            
    def watch (self):
        """Do a screen watch operation, i.e., update the screen to
        reflect the buffer contents around the current dot, in curses mode.
        """
        if not cursespresent:
            return
        self.enable_curses ()
        curlinenum = self.curline
        width, height = self.watchparams[1], self.watchparams[2]
        lines, currow, curcol = self.screentext (height, width, curlinenum)
        if currow >= height:
            currow = height - 1
        if curcol >= width:
            curcol = width - 1
        for row, line in enumerate (lines):
            line, wrap = line
            screen.addstr (row, 0, line)
            screen.clrtoeol ()
        screen.clrtobot ()
        if not self.screenok:
            screen.clearok (1)
            self.screenok = True
        screen.move (currow, curcol)
        screen.refresh ()
        
    # Interface to the display thread
    def startdisplay (self):
        """Start the wxPython display (GT40 emulation, essentially).
        This is a NOP if wxPython is not available.
        """
        if not display:
            atexit.register (enddisplay)
            # Release the main thread, allowing it to start the display
            dsem.release ()
        else:
            self.updatedisplay ()

    def updatedisplay (self):
        """Refresh the GT40 style display to reflect the current
        buffer state around dot.
        """
        if display:
            display.show ()
            
    def hidedisplay (self):
        """Turn off (hide) the GT40 display.
        """
        if display:
            display.show (False)
    
    def autoverify (self, flag):
        """Handle automatic verify for the ES and EV flags.  The input
        is the flag in question.
        """
        if flag:
            if flag == -1:
                flag = 0
            ch = flag & 255
            if ch:
                if ch < 32:
                    ch = lf
                else:
                    ch = chr (ch)
            flag >>= 8
            start = self.buffer.line (-flag)
            end = self.buffer.line (flag + 1)
            sys.stdout.write (printable (self.buf[start:self.dot]))
            if ch:
                sys.stdout.write (ch)
            sys.stdout.write (printable (self.buf[self.dot:end]))            
            sys.stdout.flush ()
            self.screenok = False

# A metaclass to allow non-alphanumeric methods to be defined, which
# is handy when you use method names directly for command character
# processing.  Inspired by the Python Cookbook, chapter 20 intro.
def _repchar (m):
    return chr (int (m.group (1), 8))
class Anychar (type):
    def __new__ (cls, cname, cbases, cdict):
        newnames = {}
        charre = re.compile ("char([0-7]{3})")
        for name in cdict:
            newname, cnt = charre.subn (_repchar, name)
            if cnt:
                fun = cdict[name]
                newnames[newname] = fun
        cdict.update (newnames)
        return super (Anychar, cls).__new__ (cls, cname, cbases, cdict)

class qreg (object):
    '''Queue register object.  Stores text and numeric parts, with
    methods to access each part.
    '''
    def __init__ (self):
        self.num = 0
        self.text = ""

    def getnum (self):
        return self.num

    def setnum (self, val):
        self.num = val

    def getstr (self):
        return self.text

    def setstr (self, val):
        self.text = val

    def appendstr (self, val):
        self.text += val

# Atexit handlers.  These are guarded so they can be called even
# if the corresponding module isn't present.
def endwin ():
    """Close down curses mode.
    """
    global screen
    if screen:
        try:
            curses.endwin ()
        except:
            pass
        screen = None
        
def enddisplay ():
    """Stop wxPython display.
    """
    global display
    if display:
        display.stop ()
            
if wxpresent:
    pointsize = 12

    class displayApp ():
        """This class wraps the App main loop for wxPython.

        Due to limitations in some OS (Mac OS at least), this
        class must be created in the main thread -- the first
        thread of the process.  Furthermore, the "start" method
        will create the application and run the main loop, and will
        not return until application exit.  So for any other things
        that need to run in the meantime, like user interaction,
        the caller will need to create an additional thread.
        
        This class creates a 24 by 80 character window, and initializes
        some common state such as the font used to display text
        in the window.  
        """
        
        def __init__ (self, teco):
            self.running = False
            self.teco = teco
            self.displayline = 16
    
        def start (self):
            """Start the wx App main loop.
            This finds a font, then opens up a Frame initially
            sized for 80 by 24 characters.
            """
            global display
            self.app = wx.App ()
            self.font = wx.Font (pointsize, wx.FONTFAMILY_MODERN,
                                 wx.FONTSTYLE_NORMAL,
                                 wx.FONTWEIGHT_NORMAL)
            dc = wx.MemoryDC ()
            dc.SetFont (self.font)
            self.fontextent = dc.GetTextExtent ("a")
            cw, ch = self.fontextent
            self.margin = cw
            cw = cw * 80 + self.margin * 2
            ch = ch * 24 + self.margin * 2
            self.frame = displayframe (self, wx.ID_ANY, "TECO display",
                                       wx.Size (cw, ch))
            self.frame.Show (True)
            self.running = True
            self.app.MainLoop ()
            # Come here only on application exit.
            display = None
    
        def show (self, show = True):
            """If the display is active, this refreshes it to display
            the current text around dot.  If "show" is False, it tells
            the display to go hide itself.
            """
            if self.running:
                self.frame.doShow = show
                self.frame.doRefresh = True
                wx.WakeUpIdle ()
    
        def stop (self):
            """Stop the display thread by closing the Frame.
            """
            if self.running:
                self.running = False
                self.frame.AddPendingEvent (wx.CloseEvent (wx.wxEVT_CLOSE_WINDOW))
                
    class displayframe (wx.Frame):
        """Simple text display window class derived from wxFrame.
        It handles repaint, close, and timer events.  The timer
        event is used for the blinking text cursor.

        When instantiated, this class creats the window using the
        supplied size, and starts the cursor blink timer.
        """
        def __init__ (self, display, id, name, size):
            framestyle = (wx.MINIMIZE_BOX |
                          wx.MAXIMIZE_BOX |
                          wx.RESIZE_BORDER |
                          wx.SYSTEM_MENU |
                          wx.CAPTION |
                          wx.CLOSE_BOX |
                          wx.FULL_REPAINT_ON_RESIZE)
            wx.Frame.__init__ (self, None, id, name, style = framestyle)
            self.SetClientSize (size)
            timerId = 666
            self.Bind (wx.EVT_PAINT, self.OnPaint)
            self.Bind (wx.EVT_CLOSE, self.OnClose)
            self.Bind (wx.EVT_TIMER, self.OnTimer)
            self.Bind (wx.EVT_IDLE, self.OnIdle)
            self.display = display
            self.cursor = None, None, False
            self.timer = wx.Timer (self, timerId)
            self.timer.Start (500)
            self.cursorState = True
            self.doRefresh = False
            self.SetBackgroundColour (wx.WHITE)
            
        def OnIdle (self, event = None):
            """Used to make a refresh happen, if one has been requested.
            """
            if self.doRefresh:
                self.doRefresh = False
                self.Show (self.doShow)
                if self.doShow:
                    self.Refresh ()
                
        def OnTimer (self, event = None):
            """Draw a GT40-TECO style cursor: vertical line with
            a narrow horizontal line across the bottom, essentially
            an upside-down T.

            If dot is between a CR and LF, the cursor is drawn upside
            down (right side up T) at the left margin.
            """
            x, y, flip = self.cursor
            if x is not None:
                cw, ch = self.display.fontextent
                if self.cursorState:
                    pen = wx.BLACK_PEN
                else:
                    pen = wx.WHITE_PEN
                self.cursorState = not self.cursorState
                dc = wx.ClientDC (self)
                dc.SetPen (pen)
                if flip:
                    dc.DrawLine (x, y, x, y - ch)
                    dc.DrawLine (x - cw / 2, y - ch, x + cw / 2 + 1, y - ch)
                else:
                    dc.DrawLine (x, y, x, y - ch)
                    dc.DrawLine (x - cw / 2, y, x + cw / 2 + 1, y)
                
        def OnPaint (self, event = None):
            """This is the event handler for window repaint events,
            which is also done on window resize.  It fills the window
            with the buffer contents, centered on dot.

            Line wrap is indicated in GT40 fashion: the continuation line
            segments have a right-pointing arrow in the left margin.
            """
            dc = wx.PaintDC (self)
            dc.Clear ()
            dc.SetFont (self.display.font)
            w, h = dc.GetSize ()
            w -= 2 * self.display.margin
            h -= 2 * self.display.margin
            cw, ch = self.display.fontextent
            w //= cw
            h //= ch
            lines, currow, curcol = self.display.teco.screentext (h, w, h // 2)
            if curcol > len (lines[currow][0]):
                self.cursor = self.display.margin, \
                              (currow + 2) * ch + self.display.margin, \
                              True
            else:
                self.cursor = curcol * cw + self.display.margin, \
                              (currow + 1) * ch + self.display.margin, \
                              False
            wrap = False
            dc.SetPen (wx.BLACK_PEN)
            for row, line in enumerate (lines):
                y = self.display.margin + row * ch
                if wrap:
                    y2 = y + ch - ch / 2
                    dc.DrawLine (1, y2, cw - 1, y2)
                    dc.DrawLines ([ wx.Point (cw / 2, y2 - cw / 3),
                                    wx.Point (cw - 1, y2),
                                    wx.Point (cw / 2, y2 + cw / 3 + 1)])
                line, wrap = line
                dc.DrawText (line, self.display.margin, y)
    
        def OnClose (self, event = None):
            """Close the GT40 window, and stop the cursor blink timer.
            """
            self.timer.Stop ()
            self.cursor = None, None
            self.Destroy ()
            
# Nice hairy regexp for scanning across bracketed constructs looking
# for the end of a range (conditional or iteration).  It doesn't bother
# looking for parentheses since none of the constructs we have to scan 
# for ("else" or condition end, or iteration end, or label) are allowed
# inside parentheses -- and it isn't the job of this scanner to catch
# illegal commands.  For the same reason, it doesn't do things like
# look for missing arguments, or invalid q-reg names, etc.
#
# The recipe here goes like this: the first half is for @-modified commands,
# so it matches string arguments wrapped in matching delimiters.
# The second half is the corresponding set of rules for non-@-modified
# commands, so they have escape as the string terminator, except for
# those oddballs that use something else, like ctrl/a.  It also covers
# the cases of commands that don't take string arguments and thus
# don't care about @ modifiers
#
# The indenting is meant to show grouping.  This pattern must be compiled
# with the "verbose" flag.
#
# This pattern is subsequently modified to make three very similar patterns:
# one to scan across iterations, one to scan across conditionals, and
# one to search for tags (labels).  A single base pattern is used to
# form all three, so I don't have to keep three almost-identical copies
# of these things in sync.
basepat = """
          # First any commands that take string arguments, @ modified flavor
          (?:(?:@(?:\\:*(?:(?:f(?:(?:[cns_](.).*?\\1.*?\\1)|
                                  (?:[br](.).*?\\2)|
                                  .))|
                           (?:e(?:[bginrw_](.).*?\\3|.))|
                           # Control A and Control U in uparrow form
                           (?:\\^(?:(?:a(.).*?\\4)|
                                    (?:u\\.?.(.).*?\\5)|.))|
                           # Tag start is included here, so tags are skipped
                           # The ! is removed for tag search so tags are
                           # not skipped there.
                           (?:[\001!inos_](.).*?\\6)|
                           (?:\025\\.?.(.).*?\\7))))|
              # Next commands that take string arguments, no @
              (?:(?:f(?:(?:[cns_].*?\033.*?\033)|
                        (?:[br].*?\033)|
                        .))|
                 (?:e(?:[bginrw_].*?\033|.))|
                 # Control A, Control U, Control ^ in uparrow form
                 (?:\\^(?:(?:a.*?\001)|
                          (?:u\\.?..*?\025)|
                          (?:\\^.)|.))|
                 (?:[inos_].*?\033)|
                 (?:\001.*?\001)|
                 # At this point we insert one of several subexpressions,
                 # depending on what we need: a pattern to skip tags,
                 # or a pattern to skip condition starts, or both, or
                 # neither
                 ### insert here
                 (?:\025\\.?..*?\033)|
                 (?:\036.)|
                 (?:[][%gmqux]\\.?.)|
                 # The tilde is replaced by the terminator character set
                 [^~]))*
              """
# These two can be inserted into basepat at "### insert here"
marker = "### insert here"
exclpat = "(?:!.*?!)|"
dqpat  = '(?:".)|'

# These are the terminator sets, inserted at two places into basepat to 
# specify what set of characters terminates the scan
iterset = "<>"
condset = "\"|\'<>"
tagset = "!<>"

# Construct the three patterns
iterpat = basepat.replace (marker, exclpat + dqpat).replace ('~', iterset)
condpat = basepat.replace (marker, exclpat).replace ('~', condset)
tagpat  = basepat.replace ("!", "").replace (marker, dqpat).replace ('~', tagset)

iterre = re.compile (iterpat, re.IGNORECASE | re.DOTALL | re.VERBOSE)
condre = re.compile (condpat, re.IGNORECASE | re.DOTALL | re.VERBOSE)
tagre  = re.compile (tagpat,  re.IGNORECASE | re.DOTALL | re.VERBOSE)

class iter (object):
    '''State for command iterations.
    '''
    def __init__ (self, teco, cmd, count):
        self.start = cmd.cmdpos
        self.count = count
        self.cmd = cmd
        self.teco = teco

    def again (self, atend = True, delta = 1):
        if self.count:
            self.count -= delta
            if not self.count:
                if not atend:
                    self.cmd.skipiter ()
                    if self.teco.trace:
                        sys.stdout.write ('>')
                        sys.stdout.flush ()
                self.cmd.iterstack.pop ()
                return
        self.cmd.cmdpos = self.start
        self.teco.clearargs ()

# assorted regular expressions used below:

# patterns for \ command, for the three possible radix values
decre = re.compile (r'[+-]?\d+')
octre = re.compile (r'[+-]?[0-7]+')
hexre = re.compile (r'[+-]?[0-9a-f]+', re.IGNORECASE)

# Patterns for the string builder, with and without ^x to control-x
# conversion.  Note that a single replacer function is used with
# either pattern, so bldpat must be a superset of buildpatnoup,
# and the common groups must come first and in the same order.
_bldpat = re.compile('''
                     (?:(?:(?:\\^[qr])|[\021\022])(.))|   # ^Qx or ^Rx
                     (?:(?:(?:\\^e)|\005)q(\\.?.))|       # ^EQq
                     (?:(?:(?:\\^e)|\005)u(\\.?.))|       # ^EUq
                     (?:(?:(?:\\^v)|\026)(.))|            # ^Vx
                     (?:(?:(?:\\^w)|\027)(.))|            # ^Wx
                     (?:\\^(.))                           # ^x
                     ''', re.IGNORECASE |re.DOTALL | re.VERBOSE)
_bldpatnoup = re.compile('''
                     (?:[\021\022](.))|                   # ^Qx or ^Rx
                     (?:\005q(\\.?.))|                    # ^EQq
                     (?:\005u(\\.?.))|                    # ^EUq
                     (?:\026(.))|                         # ^Vx
                     (?:\027(.))                          # ^Wx
                     ''', re.IGNORECASE | re.DOTALL | re.VERBOSE)

# pattern for the search string to search regexp converter
_searchpat = re.compile ('''
                         # A regexp special character (must be quoted)
                         ([][\\\\^$.?+(){}])|
                         # ^ES -- One or more spaces/tabs; ^EX -- any char
                         # These two do not accept ^N
                         ((?:\005[sx])|\030)|
                         # Check for leading ^N (inverse match)
                         (?:(\016)?
                            (?:
                               # ^EGq -- table match, with optional ^N
                               (?:\005g(\\.?.))|
                               # All other special match characters
                               ((?:\005[abcdlrvwx])|\023)))|
                         # Check for ^EE -- regexp match (teco.py addition)
                         (?:\005e(.+))
                         ''', re.IGNORECASE | re.DOTALL | re.VERBOSE)

# Substitution dictionary for the special match characters
#
# These are regexp subexpressions corresponding to TECO match patterns
_searchdict2 = { ctrle + "s" : "[ \t]+",
                 ctrle + "x" : ".",
                 ctrlx       : "." }

# These are rexexp character class expressions, so they go inside
# [...], or [^...] if ^N was present in the TECO string
_searchdict5 = { ctrle + "a" : "A-Za-z",
                 ctrle + "b" : "\\W",
                 ctrle + "c" : "\\w$_.",
                 ctrle + "d" : "\d",
                 ctrle + "l" : eol,
                 ctrle + "r" : "\\w",
                 ctrle + "v" : "a-z",
                 ctrle + "w" : "A-Z",
                 ctrls       : "\\W"}

class command_level(metaclass=Anychar):
    '''This state handles a single command level (interactive or macro
    execution) for TECO.

    Any method with a one-character name is the handler for the
    corresponding TECO command.  Two-character methods are for two-
    character TECO command names (the dispatch is via the one-character
    method matching the start character; for example method "fb" is
    invoked via method "f").

    TECO command characters that are not valid Python symbol names
    are represented by methods with "charnnn" in the name.  The metaclass
    creates synonyms for those methods with the real name, which is
    the character with octal char code nnn.  For example, char042 is
    the " (double quote) command method, and fchar074 is the f< command
    method.
    '''
    def __init__ (self, teco, q = None):
        self.qregs = q or { }
        self.teco = teco
        self.enlist = [ ]
        self.enstring = ""
        self.iterstack = [ ]
        
    # Define a bunch of properties for cleaner access to state that
    # is kept in other places.
    # First the ones that are common across all command levels, and
    # are kept by the "teco" class:
    atmod = commonprop ("atmod")
    arg2 = commonprop ("arg2")
    colons = commonprop ("colons")
    ctrlxflag = commonprop (ctrlx)
    edflag = commonprop ("ed")
    etflag = commonprop ("et")
    radix = commonprop ("radix")
    laststringlen = commonprop ("laststringlen")
    lastsearch = commonprop ("lastsearch")
    lastfilename = commonprop ("lastfilename")
    trace = commonprop ("trace")
    buffer = commonprop ("buffer")
    screenok = commonprop ("screenok")
    
    # Now the ones that relate to the text buffer, so they are kept
    # by the "buffer" class:
    buf = bufprop ("text")
    dot = bufprop ("dot")
    end = bufprop ("end")
    eoflag = bufprop ("eoflag")
    ffflag = bufprop ("ffflag")
    
    def do (self, c):
        """Execute the single teco command named by the argument
        (a single character, or a two-character string for TECO
        commands that have two character names).  The method for that
        command is invoked, if it exists; otherwise error ILL
        (Illegal command) is raised.

        The command name is passed as argument to the method, which is
        useful when several commands (e.g., all the digits) are
        bound to a single method.
        """
        c = c.lower ()
        try:
            op = getattr (self, c)
        except AttributeError:
            raise ILL (self.teco, c)
        op (c)
    
    def tracechar (self, c):
        """Show the supplied character (or string) as trace text,
        if tracing is enabled.
        """
        if self.trace:
            sys.stdout.write (printable (c))
            sys.stdout.flush ()
        
    def peeknextcmd (self):
        """Look at the next command character, without advancing
        the current command pointer.
        """
        try:
            return self.command[self.cmdpos]
        except IndexError:
            return ""
    
    def nextcmd (self):
        """Get the next command character; if there isn't one,
        error UTC (Unterminated Command) is raised.
        """
        c = self.peeknextcmd ()
        if not c:
            raise UTC (self.teco)
        self.tracechar (c)
        self.cmdpos += 1
        return c

    def colon (self):
        """Return True if colon modifier(s) are present.
        """
        return self.colons != 0
    
    def getarg (self, c, default = None):
        '''Get the command argument.  If there is no argument, the
        default argument governs what happens.  If no default is
        supplied, the function returns None.  If a default value is
        supplied, that value is returned.  Otherwise, the default argument
        should be an exception class, and that exception is raised.
        This function is used for cases where the command does not return
        a value; it requires that any argument is complete (matching
        parentheses, right hand side present for a pending operator).
        '''
        ret = self.teco.getarg (c)
        if default is not None:
            self.clearargs ()
            if ret is None:
                # Yuck.  If exceptions were new style classes
                # I wouldn't need this ugly mess!
                if type (default) is type (Exception):
                    raise default (self.teco)
                ret = default
        return ret

    def getoptarg (self, c):
        '''Get the command argument.  Return None if it was not present.
        This function may be called when we are in the middle of an
        expression; that is intended for the case where a command may return
        a value that is then in turn part of an expression.
        '''
        return self.teco.getoptarg (c)
    
    def getargs (self, c, default = None):
        """Get the command argument pair, as a pair.  If there was
        only one argument, the first element of the pair is None.
        If there was no argument at all, or nothing after the comma,
        the supplied default is used for the second element of the pair
        in the same way as for method getarg.
        """
        arg2 = self.arg2
        return arg2, self.getarg (c, default)
    
    def getargc (self, c, default = None):
        """Get the command argument and the colon modifier, as a pair.
        If there was no argument, the supplied default is used for the
        first element of the pair in the same way as for method getarg.
        """
        col = self.colon ()
        return self.getarg (c, default), col
    
    def getargsc (self, c, default = None):
        """Get the command argument pair and the colon flag, as a tuple.
        If there was only one argument, the first element of the pair is None.
        If there was no argument at all, or nothing after the comma,
        the supplied default is used for the second element of the pair
        in the same way as for method getarg.
        """
        arg2 = self.arg2
        col = self.colon ()
        return arg2, self.getarg (c, default), col

    def setval (self, n):
        """Set the command result value into the expression state.
        """
        self.teco.setval (n)
        
    def clearargs (self):
        """Clear the expression state and command modifiers.
        """
        self.teco.clearargs ()

    def clearmods (self):
        """Clear the command modifier flags (colon and at sign).
        """
        self.teco.clearmods ()

    def bitflag (self, c):
        """Process a bit flag command, such as ET.  See teco.bitflag
        for details.
        """
        self.teco.bitflag (c)

    def numflag (self, c):
        """Process a numeric flag command, such as EV.  See teco.numflag
        for details.
        """
        self.teco.numflag (c)
        
    def strarg (self, c, term = esc):
        """Return the string argument for the command.  If the at sign
        modifier is in effect, the next character in the command string
        is the delimiter.  Otherwise, the term argument specifies the
        delimiter, or ESC is used if term is omitted.
        """
        if self.atmod:
            term = self.nextcmd ()
            self.atmod = False
        s = self.cmdpos
        try:
            e = self.command.index (term, s)
        except ValueError:
            raise UTC (self.teco, c)
        self.cmdpos = e + 1
        self.tracechar (self.command[s:self.cmdpos])
        return self.command[s:e]

    def strargs (self, c):
        """Return a pair of string arguments for the command.  If the at 
        sign modifier is in effect, the next character in the command 
        string is the delimiter.  Otherwise, the delimiter is ESC.
        """
        term = esc
        if self.atmod:
            term = self.peeknextcmd ()
        s1 = self.strarg (c)
        return s1, self.strarg (c, term)

    def makecontrol (self, c):
        """Return the control character correponding to the supplied
        character; for example, 'a' produces control/A.
        """
        n = ord (c)
        if 0o100 <= n <= 0o137 or 0o141 <= n <= 0o172:
            return chr (n & 31)
        else:
            raise IUC (self.teco, chr (n))
        
    def _strbuildrep (self, m):
        if m.group (1):
            # ^Qx or ^Rx is literally x
            return m.group (1)
        elif m.group (2):
            # ^EQq is text of Q-reg q
            return self.qregstr (m.group (2))
        elif m.group (3):
            # ^EUq is character whose code is in numeric Q-reg q
            return chr (self.qreg (m.group (3)).getnum ())
        elif m.group (4):
            # ^Vx is lowercase x
            return m.group (4).lower ()
        elif m.group (5):
            # ^Vx is uppercase x
            return m.group (5).upper ()
        else:
            # ^x is control-x
            return self.makecontrol (m.group (6))
        
    def strbuild (self, s):
        """TECO string builder.  This processes uparrow/char combinations,
        unless bit 0 in ED is set.  It also handles string build
        characters such as ^Qx (literal x), ^EQq (text in q-reg q), etc.
        """
        if self.edflag & 1:
            pat = _bldpatnoup
        else:
            pat = _bldpat
        return pat.sub (self._strbuildrep, s)

    def _str2rerep (self, m):
        if m.group (1):
            return '\\' + m.group (1)
        elif m.group (2):
            return _searchdict2[m.group (2).lower ()]
        
        inverse = m.group (3) is not None
        if m.group (4):
            # ^EGq -- table match
            charset = set (self.qregstr (m.group (4)))
            pfx = sfx = ''
            if not charset:
                return ""
            if not inverse and len (charset) == 1:
                c = ''.join (charset)
                if c in "][\\^$.?+(){}":
                    c = '\\' + c
                return c
            if ']' in charset:
                charset -= set (']')
                pfx = ']'
            if '\\' in charset:
                charset -= set ('\\')
                pfx += '\\'
            if '-' in charset:
                sfx = '-'
                charset -= set ('-')
            c = pfx + ''.join (charset) + sfx
        elif m.group (5):
            c = _searchdict5[m.group (5).lower ()]
        else:
            # ^EE -- regexp pattern.  Return it exactly as written.
            return m.group (6)
        if inverse:
            return "[^%s]" % c
        else:
            return "[%s]" % c

    def str2re (self, s):
        """Convert a TECO search string to the equivalent
        regular expression string.
        """
        reflags = re.DOTALL
        if self.ctrlxflag == 0:
            reflags |= re.IGNORECASE
        return re.compile (_searchpat.sub (self._str2rerep, s), reflags)

    def isinteractive (self):
        '''Return True if executing at the interactive level
        as opposed to in a macro.
        '''
        return self is self.teco.interactive
    
    def skip (self, pat):
        '''Skip based on a regexp, starting at the current command
        position.  Updates command position to be one character beyond
        the end of the match, and returns the character after the match,
        if any.  If no match, returns None.

        The reason for passing over an extra character is that the regexp
        is coded to terminate on one of the characters we want to look
        for -- for example, ! < > for tag search.  It would make sense
        to include that set at the end of the regexp, but if you do that
        then the match attempt can take a very long time if there is no
        match.  (It seems to take exponential time!)  To avoid that,
        the regexp instead describes what we want to skip, and then
        picks up, skips over, and returns the character after that.
        '''
        m = pat.match (self.command, self.cmdpos)
        if not m:
            return None
        self.cmdpos = m.end () + 1
        try:
            return self.command[self.cmdpos - 1]
        except IndexError:
            return None
    
    def skipiter (self):
        '''Skip across nested iterations to the end of the current
        iteration.
        '''
        level = 1
        while level > 0:
            tail = self.skip (iterre)
            if not tail:
                raise UTC (self.teco, '<')
            if tail == '<':
                level += 1
            else:
                level -= 1
                
    def skipcond (self, c):
        '''Skip across conditional code for the specified end string.
        Nested conditionals are skipped.  Nested iterations are
        skipped but scanned, because iterations can overlap conditionals.
        '''
        while True:
            tail = self.skip (condre)
            if not tail:
                raise MAP (self.teco)
            if tail in c:
                break
            else:
                # We stopped on something other than what we wanted to skip to.
                # There are two possibilities: it is the start of an inner 
                # range (either condition or iteration), or it is the end
                # of some range.
                #
                # We can't just recursively skip nested ranges because
                # of this warped case:
                #       < 0A"A C > '
                #
                # So instead, nested conditions are just skipped, but
                # iterations are handled by stacking a simulated start of
                # iteration with a repeat count of one onto the iteration
                # stack and continuing the scan in-line.  The count of
                # one means that this case also works somewhat sanely:
                #       "A < xxx ' >
                # I suspect that's not legal, but who knows...
                if tail == '<':
                    self.iterstack.append (iter (self.teco, self, 1))
                elif tail == '"':
                    self.cmdpos += 1
                    self.skipcond ("'")
                elif tail == '>':
                    # Found an iteration end.  Pop it off the iteration stack
                    try:
                        self.iterstack.pop ()
                    except IndexError:
                        raise BNI (self.teco)
    
    def findtag (self, c):
        '''Search for the specified tag, starting at the current
        command position.  Nested iterations are skipped (not searched),
        so if the tag is in one of those it will not be found.
        '''
        while True:
            tail = self.skip (tagre)
            if not tail:
                raise TAG (self.teco, c)
            if tail == '!':
                term = '!'
                if self.command[self.cmdpos-2] == '@':
                    term = self.nextcmd ()
                if self.command.startswith (c + term, self.cmdpos):
                    self.cmdpos += len (c) + 1
                    return
                try:
                    e = self.command.index (term, self.cmdpos)
                    self.cmdpos = e + 1
                except ValueError:
                    raise UTC (self.teco, '!')
            elif tail == '<':
                p = self.cmdpos
                self.skipiter ()
            else:
                # Found an iteration end.  Pop it off the iteration stack
                try:
                    self.iterstack.pop ()
                except IndexError:
                    raise BNI (self.teco)

    def run (self, s):
        self.command = s
        self.cmdpos = 0
        self.iterstack = [ ]
        try:
            while self.cmdpos < len (self.command):
                c = self.nextcmd ()
                self.do (c)
        except ExitLevel:
            pass
        except KeyboardInterrupt:
            raise XAB (self.teco)

    def search (self, s, n, start, end, colon, topiffail = True,
                nextpage = None):
        """Search in the current buffer for a given string.
        Stop on the abs(n)th occurrence.  If n is negative, search
        is backward, starting at 'end'; otherwise it is forward,
        starting at 'start'.  The search range is bounded by
        the range (start, end).  If 'nextpage' is specified, it is
        called if we run out of stuff to match in the current buffer,
        continuing until end of file.  Note that 'nextpage' is only
        meaningful for forward searches (n > 0); it is ignored for
        backward searches.

        Note: start and end are the range of buffer positions where
        the match is allowed to begin, inclusive.
        
        If the search succeeds, dot is set to the end of the
        match string, and the ^S variable is set to the negative of
        the matched length.  (I.e., .+^S is the start of the match.)
        Finally, if 'colon' is true, the current arg is set to -1.

        If the search fails, a bunch of things can happen.

        If topiffail is True or omitted, and the 16 bit is clear in
        the ED flag, dot is set to zero.

        If 'colon' is true, the current arg is set to 0.
        The same happens if we're in an iteration, and the next command
        character is a semicolon.

        Otherwise, if we're in an iteration, a warning message is
        generated and the iteration is exited (as if a semicolon
        had been next).  If we're not in an iteration, an error
        ?SRH is generated.
        """
        rep = abs (n)
        if n < 0:
            pos = end
            laststart = None
            # We don't allow paging for reverse searches
            nextpage = None
        else:
            pos = start
        if s:
            s = self.strbuild (s)
            self.lastsearch = s
        else:
            s = self.lastsearch
        re = self.str2re (s)
        # Bind the buffer text to a local variable to help speed
        # up the inner loop
        buf = self.buf
        while rep:
            if n < 0:
                # This is painful.  There is no reverse search for
                # regular expressions, so we do it the hard way,
                # by repeatedly matching, stepping backwards one
                # character at a time...
                #
                # Note to self: a different way that's probably faster
                # but harder to do: reverse the string, reverse the
                # regexp pattern, "unreverse" any [...] and [...]+
                # inside the regexp, and do an ordinary search with those.
                # Then some extra work is needed to find any matches
                # that straddle the search start point (i.e., dot).
                tmatch = re.match (buf, pos)
                if tmatch and not (laststart and tmatch.end () > laststart):
                    match = tmatch
                    laststart = match.start ()
                else:
                    if pos:
                        pos -= 1
                        continue
                    match = None
            else:
                match = re.search (buf, pos)
            if match and not start <= match.start () <= end:
                match = None
            if match is None:
                # If we have a nextpage function and we're not
                # at the end of the input file, keep going
                if nextpage and self.eoflag == 0:
                    nextpage ()
                    buf = self.buf
                    start = 0
                    pos = 0
                    end = self.end
                    continue
                if topiffail and (self.edflag & 16) == 0:
                    self.buffer.goto (0)
                if colon:
                    self.setval (0)
                    return False
                elif self.iterstack:
                    self.setval (0)
                    if self.peeknextcmd () != ';':
                        print("%Search fail in iter")
                        # pretend there was a ;
                        self.do (';')
                    return False
                else:
                    raise SRH (self.teco, s)
            rep -= 1

        # We found what we were looking for.  "match" is a regexp
        # match object for the matched string.
        self.buffer.goto (match.end ())
        self.laststringlen = -(match.end () - match.start ())
        # Supply the success value if asked for, or if a ; follows
        if colon or self.iterstack and self.peeknextcmd () == ';':
            self.setval (-1)
        self.teco.autoverify (self.teco.es)
        return True
    
    def failedcommand (self):
        """Return the command string up to the point where execution
        was aborted.
        """
        return self.command[:self.cmdpos]

    def lastcommand (self):
        """Return the command string, in full.
        """
        return self.command

    def qregname (self):
        """Parse a Q-register name from the command string.  If the
        next character is dot, the name is dot plus the character
        after that; otherwise it is just the next character.

        Note that the name is not validated here; the caller does that
        if necessary.
        """
        c = self.nextcmd ()
        if c == '.':
            c += self.nextcmd ()
        return c.lower ()

    def qdict (self, c):
        """Return the Q-reg dictionary referenced by the supplied Q-reg
        name.  If the Q-reg name begins with dot, this is the local
        Q-reg dictionary for the current command level; otherwise it
        is the TECO-global dictionary.

        Note that the per-level dictionary is not necessarily unique
        to the level; a colon-modified M command creates a new one,
        an unmodified M command binds to the one of the invoking level.
        """
        if c.isalnum ():
            return self.teco.qregs
        elif c[0] == '.' and c[1].isalnum ():
            return self.qregs
        else:
            raise IQN (self.teco, c)
        
    def qreg (self, c = None):
        """Return the Q-reg named by the argument, or by the command
        string if the argument is omitted.  If the Q-reg does not yet
        exist, it is created (with no text and 0 numeric value).
        """
        if c:
            c = c.lower ()
        else:
            c = self.qregname ()
        qd = self.qdict (c)
        if c not in qd:
            qd[c] = qreg ()
        return qd[c]

    def qregstr (self, c = None):
        '''Return the string value of the specified Q-register,
        or the last filename string if *, or the last search string
        if _ was specified for the Q-register name.
        '''
        if c is None:
            t = self.peeknextcmd ()
            if t in "*_":
                c = t
                self.nextcmd ()
        if c == '*':
            return self.lastfilename
        elif c == '_':
            return self.lastsearch
        else:
            return self.qreg (c).getstr ()
        
    def setqreg (self, q):
        """Set the Q-reg named by the command string to be the supplied
        Q-reg.  This is used by the ]q (pop Q-reg) command.
        """
        c = self.qregname ()
        qd = self.qdict (c)
        qd[c] = q

    # From here on we have the actual command handlers.  Their names
    # come in two forms.  Commands whose names are alphabetic are
    # given by functions whose names are simply the command name.
    # Other commands are given by functions whose names contain
    # "charnnn" where nnn is the octal character code.
    
    # a few control chars, and space, are nop
    def nop (self, c): pass
    char000 = nop             # null (^@)
    char070 = nop             # bell (^G)
    char012 = nop             # line feed (^J)
    char014 = nop             # form feed (^L)
    char015 = nop             # carriage return (^M)
    char040 = nop             # space

    def char001 (self, c):    # ^A
        """^A command -- print text.
        """
        s = self.strarg (c, '\001')
        sys.stdout.write (s)
        sys.stdout.flush ()
        self.screenok = False
        self.clearargs ()

    def char002 (self, c):    # ^B
        """Return the current date.  Since we pretend to be RT-11 it
        would make sense to return the RT-11 format date, but that
        utterly falls apart starting with 2004 (32 years from 1972)
        so use the RSX/VMS format instead, which is substantially
        more Y2K-proof.
        """
        now = time.localtime ()
        self.setval ((now.tm_year - 1900) * 512 + now.tm_mon * 32 + now.tm_mday)
        
    def char003 (self, c):    # ^C
        """^C command -- exit TECO if done at the interactive level;
        stop execution and return to interactive prompt otherwise.
        """
        if self.isinteractive ():
            self.exit ()
        else:
            raise ExitExecution

    def char004 (self, c):    # ^D
        """^D command -- set radix to decimal.
        """
        self.radix = 10
        self.clearargs ()

    def char005 (self, c):    # ^E
        """^E command -- return form feed flag.
        """
        self.setval (self.ffflag)

    def char006 (self, c):    # ^F
        """^F command -- return switch register.  We just make it zero
        for lack of switches...
        """
        self.setval (0)

    def char010 (self, c):    # ^H
        """Return the current time of day.  Match ^B, so we'll do
        RSX/VMS format here, too.  Amusingly, that happens to be
        the RT-11 format, too.
        """
        now = time.localtime ()
        self.setval (now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec)

    def char011 (self, c):    # tab
        """Tab command -- insert text including the leading tab.
        """
        s = self.strarg (c)
        self.buffer.insert (tab + s)
        self.clearargs ()

    def char016 (self, c):    # ^N
        """^N command -- return end of file flag.
        """
        self.setval (self.eoflag)

    def char017 (self, c):    # ^O
        """^O command -- set radix to octal.
        """
        self.radix = 8
        self.clearargs ()

    def char021 (self, c):    # ^Q
        """^Q command -- return character offset corresponding to
        the line offset supplied as the argument.
        """
        self.setval (self.buffer.line (self.getarg (c, 1)))

    def char022 (self, c):    # ^R
        """^R -- Set the radix to the supplied value, which must
        be 8, 10, or 16.
        """
        r = self.getoptarg (c)
        if r is None:
            self.clearmods ()
            self.setval (self.radix)
        else:
            self.clearargs ()
            if r in (8, 10, 16):
                self.radix = r
            else:
                raise IRA (self.teco)

    def char023 (self, c):    # ^S
        """^S command -- return the negative of the length of the
        last string matched, set as replacement, or inserted.
        """
        self.setval (self.laststringlen)

    def char024 (self, c):    # ^T
        """^T command.  If an argument is given, output the character
        with that numeric value (in raw mode if colon is present).
        Otherwise, read a character from input and return its
        numeric code.

        If bit 5 in ET is set, return -1 if there is no input; otherwise
        wait for it.  (TODO)
        """
        colon = self.colon ()
        n = self.getoptarg (c)
        if n is None:
            self.clearmods ()
            if (self.etflag & 32) and self.teco.cmdhandler.eifile is None:
                # TODO -- nowait char fetch from terminal
                n = -1
            else:
                n = ord (self.teco.cmdhandler.getch ())
            self.setval (n)
        else:
            self.clearargs ()
            if colon:
                sys.stdout.write (chr (n))
            else:
                sys.stdout.write (printable (chr (n)))
            self.screenok = False
            sys.stdout.flush ()

    def char025 (self, c):    # ^U
        """^U command -- set Q-reg text.
        """
        q = self.qreg ()
        s = self.strarg (c)
        if self.colon ():
            q.appendstr (s)
        else:
            q.setstr (s)
        self.clearargs ()
        
    def char026 (self, c):    # ^V
        pass

    def char027 (self, c):    # ^W
        pass

    char030 = numflag         # ^X
        
    def char031 (self, c):    # ^Y
        """^Y command -- synonym of ^S+.,.
        """
        self.clearargs ()
        self.arg2 = self.dot + self.laststringlen
        self.setval (self.dot)

    def char032 (self, c):    # ^Z
        """^Z command -- This is supposed to be total Q-reg text size.
        Just return 0 for now.
        """
        self.setval (0)

    def char033 (self, c):    # esc
        """ESCAPE -- exit the current level if $$, otherwise clear
        out any expression value and modifiers.
        """
        try:
            if self.peeknextcmd () == esc:
                raise ExitLevel
        except UTC:
            pass
        self.clearargs ()

    def char036 (self, c):    # ^^
        """^^ command -- return the numeric value of the following character
        in the command string.
        """
        self.setval (ord (self.nextcmd ()))

    def char037 (self, c):    # ^_
        """^_ command -- return one's complement of the argument.
        """
        self.setval (~self.getarg (c, NAB))
        
    def char041 (self, c):    # !
        """! command -- tag (O command target) or comment.
        """
        self.strarg (c, '!')

    def char042 (self, c):    # "
        '''" command -- conditional execution range start.
        '''
        n = self.getarg (c, NAQ)
        if 0 <= n < 0x110000:
            nc = chr (n)
        else:
            nc = ""
        c = self.nextcmd ().lower ()
        if c == 'a':
            cond = nc.isalpha ()
        elif c == 'c':
            cond = nc.isalnum () or nc in "$._"
        elif c == 'd':
            cond = nc.isdigit ()
        elif c in "efu=":
            cond = n == 0
        elif c in "g>":
            cond = n > 0
        elif c in "lst<":
            cond = n < 0
        elif c in "n":
            cond = n != 0
        elif c == 'r':
            cond = nc.isalnum ()
        elif c == 'v':
            cond = nc.islower ()
        elif c == 'w':
            cond = nc.isupper ()
        else:
            raise IQC (self.teco)
        if not cond:
            self.skipcond ("|'")
            self.tracechar (self.command[self.cmdpos - 1])
        
    def char045 (self, c):    # %
        """% command -- increment Q-reg numeric value by the specified
        amount, and return the result.
        """
        n = self.getoptarg (c)
        if n is None:
            n = 1
        q = self.qreg ()
        n += q.getnum ()
        q.setnum (n)
        self.setval (n)

    def char047 (self, c):    # '
        """' command -- conditional range end.
        """
        pass

    def char050 (self, c):    # (
        """( command -- expression grouping.
        """
        self.teco.leftparen ()

    def char051 (self, c):    # )
        """) command -- expression grouping.
        """
        self.teco.rightparen ()

    def operator (self, c):
        """Arithmetic operators.  All the operators are bound to
        this method; the command character (which is the argument)
        distinguishes them.
        """
        self.teco.operator (c)

    char043 = operator        # #
    char046 = operator        # &
    char052 = operator        # *
    char053 = operator        # +
    char055 = operator        # -
    char057 = operator        # /

    def char054 (self, c):    # ,
        """, command -- second operand marker.
        """
        if self.arg2 is None:
            n = self.getarg (c, ARG)
            if n < 0:
                raise NCA (self.teco)
            self.arg2 = n
        else:
            raise ARG (self.teco)

    def char056 (self, c):    # .
        """. command -- current buffer position.
        """
        self.setval (self.dot)
        
    def digit (self, c):
        """Digits are handled by this method.  All digit methods are
        bound to this method, and distinguished by the command
        character argument.
        """
        self.teco.digit (c)

    char060 = digit
    char061 = digit
    char062 = digit
    char063 = digit
    char064 = digit
    char065 = digit
    char066 = digit
    char067 = digit
    char070 = digit
    char071 = digit
    
    def char072 (self, c):    # :
        """: command -- modifier.
        """
        self.colons = 1
        if self.peeknextcmd () == ':':
            self.nextcmd ()
            self.colons = 2

    def char073 (self, c):    # ;
        """; command -- iteration exit.
        """
        n, colon = self.getargc (c, NAS)
        if not self.iterstack:
            raise SNI (self.teco)
        if (not colon and n >= 0) or (colon and n < 0):
            self.skipiter ()
            self.tracechar ('>')
            self.iterstack.pop ()
        
    def char074 (self, c):    # <
        """< command -- iteration start.
        """
        n = self.getarg (c)
        self.clearargs ()
        if n is None:
            self.iterstack.append (iter (self.teco, self, 0))
        elif n <= 0:
            self.skipiter ()
            self.tracechar ('>')
        else:
            self.iterstack.append (iter (self.teco, self, n))

    def char075 (self, c):    # =
        """= command -- display the argument in decimal.
        == command -- display the argument in octal.
        === command -- display the argument in hex.

        CRLF is added after the value unless : modifier is given.
        """
        n, colon = self.getargc (c, NAE)
        if colon:
            term = ""
        else:
            term = lf
        if self.peeknextcmd () == '=':
            self.nextcmd ()
            if self.peeknextcmd () == '=':
                self.nextcmd ()
                sys.stdout.write ("%x%s" % (n, term))
            else:
                sys.stdout.write ("%o%s" % (n, term))
        else:
            sys.stdout.write ("%d%s" % (n, term))
        self.screenok = False
        sys.stdout.flush ()
        
    def char076 (self, c):    # >
        """< command -- iteration end.
        """
        if not self.iterstack:
            raise BNI (self.teco)
        self.clearargs ()
        self.iterstack[-1].again ()

    def char077 (self, c):    # ?
        """? command -- toggle trace flag.
        """
        self.trace = not self.trace

    def char100 (self, c):    # @
        """@ command -- modifier (explicitly supplied string delimiter).
        """
        self.atmod = True

    def a (self, c):
        """A command -- append (if no argument) or return numeric value
        of character in the text buffer (if argument is given, which is
        the offset from dot).
        """
        n, colon = self.getargc (c)
        if n is None:
            self.clearargs ()
            ret = self.buffer.append ()
            if colon:
                self.setval (ret)
        else:
            pos = self.dot + n
            if 0 <= pos < self.end:
                self.setval (ord (self.buf[pos]))
            else:
                self.setval (-1)
    
    def b (self, c):
        """B command -- zero (start of buffer).
        """
        self.setval (0)

    def c (self, c):
        """C command -- move forward n characters.
        """
        newpos = self.dot + self.getarg (c, 1)
        if 0 <= newpos <= self.end:
            self.buffer.goto (newpos)
        else:
            raise POP (self.teco, c)
        
    def d (self, c):
        """D command -- delete n characters.  If two arguments are
        given, delete that range of characters.
        """
        # TODO: two args
        m, n = self.getargs (c, 1)
        if m is None:
            end = self.dot + n
            if 0 <= end <= self.end:
                if n < 0:
                    self.buffer.goto (end)
                    n = -n
                if n:
                    self.buffer.delete (n)
            else:
                raise POP (self.teco, c)
        else:
            if 0 <= m <= n <= self.end:
                self.buffer.goto (m)
                self.buffer.delete (n - m)
            else:
                raise POP (self.teco, c)
        self.clearmods ()
    
    def e (self, c):
        """E command -- two character command starting with E.
        """
        c = self.nextcmd ()
        try:
            self.do ('e' + c)
        except ILL:
            raise IEC (self.teco, c)

    def ea (self, c):
        """EA command -- switch to alternate output stream.
        """
        self.buffer.ea ()
    
    def eb (self, c):
        """EB command -- open file for editing (input/output, with
        backup).
        """
        fn = self.strbuild (self.strarg (c))
        colon = self.colon ()
        self.clearargs ()
        ret = self.buffer.eb (fn, colon)
        if colon:
            self.setval (ret)

    def ec (self, c):
        """EC command -- finish with the current file.  If input and
        output files are open, write remainder of the input to output,
        then close both.
        """
        self.buffer.ec ()
        self.clearargs ()

    ed = bitflag
    eh = numflag

    def ef (self, c):
        """EF command -- close current output file, without any writing.
        """
        self.buffer.ef ()

    def eg (self, c):
        """EG command -- OS dependent action.

        Right now this does nothing.
        """
        cmd = self.strbuild (self.strarg (c))
        colon = self.colon ()
        # TODO: do something
        if colon:
            self.setval (0)
            
    def ei (self, c):
        """EI command -- read command input from a file.
        """
        fn = self.strbuild (self.strarg (c))
        colon = self.colon ()
        self.clearargs ()
        ret = self.teco.cmdhandler.ei (fn, colon)
        if colon:
            self.setval (ret)
        
    def ej (self, c):
        """EJ command -- return environment parameters.
        """
        n = self.getarg (c, 0)
        if n == -1:
            self.setval (CPU * 256 + OS)
        elif n == 0:
            # Don't return too big a number or some things get confused
            # We use the parent pid, because that's fairly constant
            # for a given session -- just like the "job" number for
            # classic DEC operating systems.
            self.setval (os.getppid () & 255)
        elif n == 1:
            self.setval (0)
        elif n == 2:
            self.setval (os.getuid ())
        else:
            raise ARG (self.teco)

    def ek (self, c):
        """EK command -- discard output file.
        """
        self.buffer.ek ()
        
    def en (self, c):
        """EN command -- set wildcard pattern to match, or return
        next match value.
        """
        cmd = self.strbuild (self.strarg (c))
        colon = self.colon ()
        if len (cmd):
            self.enlist = glob.glob (cmd)
            self.enstring = cmd
        elif self.enlist:
            self.lastfilename = self.enlist[0]
            del self.enlist[0]
            if colon:
                self.setval (-1)
        else:
            if colon:
                self.setval (0)
            else:
                raise FNF (self.teco, self.enstring)
            
    def eo (self, c):
        """EO command -- return TECO version number.
        """
        self.setval (VERSION)

    def ep (self, c):
        """EP command -- set alternate input stream.
        """
        self.buffer.ep ()
    
    def er (self, c):
        """ER command -- open input file.
        """
        fn = self.strbuild (self.strarg (c))
        colon = self.colon ()
        self.clearargs ()
        ret = self.buffer.er (fn, colon)
        if colon:
            self.setval (ret)

    es = numflag
    et = bitflag
    eu = numflag
    ev = numflag
            
    def ew (self, c):
        """EW command -- open output file.
        """
        fn = self.strbuild (self.strarg (c))
        colon = self.colon ()
        self.clearargs ()
        ret = self.buffer.ew (fn, colon)
        if colon:
            self.setval (ret)

    def ex (self, c):
        """EX command -- finish with files (effect of EC command)
        then exit TECO.
        """
        self.ec (c)
        self.exit ()

    def exit (self):
        # Release the main thread, allowing it to start the display
        global exiting
        exiting = True
        if dsem:
            dsem.release ()
        sys.exit ()

    def ey (self, c = None):
        """EY command -- yank unconditionally.
        """
        self.buffer.yank (False)
    
    def f (self, c):
        """F command -- two character command starting with F.
        """
        c = self.nextcmd ()
        try:
            self.do ('f' + c)
        except ILL:
            raise IFC (self.teco, c)

    def fchar047 (self, c):    # f'
        """F' command -- 'flow' to end of conditional.
        """
        self.clearargs ()
        self.skipcond ("'")
        self.tracechar ("'")
        
    def fchar074 (self, c):    # f<
        """F< command -- 'flow' to start of iteration.  Not like
        'continue' in C, it starts another iteration without
        decrementing the count of iterations to do.
        """
        if not self.iterstack:
            raise BNI (self.teco)
        self.iterstack[-1].again (False, 0)

    def fchar076 (self, c):    # f>
        """F> command -- 'flow' to end of iteration.  Like
        'continue' in C, it decrements the count of iterations
        left to do, and does another if there are any left.
        """
        if not self.iterstack:
            raise ExitLevel
        self.iterstack[-1].again (False)

    def fb (self, c):
        """FB command -- bounded search.
        """
        s = self.strarg (c)
        m, n, colon = self.getargsc (c)
        if m is None:
            m = self.dot
            n = m + self.buffer.line (n)
        count = 1
        if m > n:
            count = -1
            m, n = n, m
        self.search (s, count, m, n, colon, False)
        
    def fc (self, c):
        """FC command -- bounded search and replace.
        """
        s, rep = self.strargs (c)
        m, n, colon = self.getargsc (c)
        self.clearargs ()
        if m is None:
            m = self.dot
            n = m + self.buffer.line (n)
        count = 1
        if m > n:
            count = -1
            m, n = n, m
        if self.search (s, count, m, n, colon, False):
            self.buffer.goto (self.dot + self.laststringlen)
            self.buffer.delete (-self.laststringlen)
            self.buffer.insert (rep)

    def fr (self, c):
        """FR command -- replace string previously matched or
        inserted with the specified string.
        """
        rep = self.strarg (c)
        self.buffer.goto (self.dot + self.laststringlen)
        self.buffer.delete (-self.laststringlen)
        self.buffer.insert (rep)
        
    def fs (self, c):
        """FS command -- search and replace.
        """
        s, rep = self.strargs (c)
        colons = self.colons
        topiffail = colons < 2
        m, n, colon = self.getargsc (c, 1)
        if not n:
            raise ISA (self.teco)
        if m == 0:
            m = None
            topiffail = False
        if n < 0:
            start, end = 0, self.dot
            if m is not None:
                start = end - abs (m)
        else:
            start, end = self.dot, self.end
            if m is not None:
                end = start + abs (m)
        if colons > 1:
            start = self.dot
            end = self.dot
        nextpage = None
        if c == "fn":
            nextpage = self.buffer.page
        elif c == "f_":
            nextpage = self.y
        if self.search (s, n, start, end, colon, topiffail, nextpage):
            self.buffer.goto (self.dot + self.laststringlen)
            self.buffer.delete (-self.laststringlen)
            self.buffer.insert (rep)
        
    fn = fs
    fchar137 = fs              # f_

    def fchar174 (self, c):    # f|
        """F| command -- 'flow' to the Else part of a conditional.
        Exits the condition if there isn't an else part.
        """
        self.clearargs ()
        self.skipcond ("|'")
        
    def g (self, c):
        """G command -- get text from the specified Q-register and
        put it in the text buffer.  Print the text if colon-modified.
        Special name * means the last file spec, _ means the last
        search string.
        """
        c = self.peeknextcmd ()
        s = self.qregstr ()
        if self.colon ():
            sys.stdout.write (s)
            sys.stdout.flush ()
            self.screenok = False
        else:
            self.buffer.insert (s)
        self.clearargs ()
            
    def h (self, c):
        """H command -- represents the wHole buffer.
        Synonym for B,Z.
        """
        self.clearargs ()
        self.arg2 = 0
        self.setval (self.end)

    def i (self,c):
        """I command -- insert a string.  If no string argument is
        supplied, inserts the character whose numeric value is
        given as the numeric argument.
        """
        n = self.getarg (c)
        s = self.strarg (c)
        if len (s) == 0:
            if n is not None:
                s = chr (n)
        elif n is not None:
            raise IIA (self.teco)
        self.buffer.insert (s)
        self.clearargs ()

    def j (self, c):
        """J command -- move to the specified offset in the buffer.
        """
        self.buffer.goto (self.getarg (c, 0))

    def k (self, c):
        """K command -- delete n lines.  If two arguments are given,
        delete the range of characters between those two positions.
        """
        m, n = self.teco.lineargs (c)
        self.buffer.goto (m)
        self.buffer.delete (n - m)
        self.clearargs ()
        
    def l (self, c):
        """L command -- move the specified number of lines.
        """
        self.buffer.goto (self.buffer.line (self.getarg (c, 1)))
        
    def m (self, c):
        """M command -- macro execution.  Executes the TECO commands
        in the specified Q-register.  If colon-modified, the new
        execution level gets its own set of local Q-registers
        (ones whose names start with . ) -- otherwise the new level
        shares the local Q-registers of the current level.
        """
        q = self.qreg ()
        if self.colon ():
            i = command_level (self.teco, self.qregs)
            self.clearmods ()
        else:
            i = command_level (self.teco)
        i.run (q.getstr ())
    
    def o (self, c):
        """O command -- go to the specified tag in the command string.
        If an argument is supplied, go to that tag in the list of tags
        given in the string argument, e.g., 2Ofoo,bar,baz$ goes to
        tag !baz!.  If the argument is out of range, execution just
        continues.
        """
        tag = self.strbuild (self.strarg (c))
        n = self.getarg (c)
        self.clearargs ()
        if not len (tag):
            raise ILL (self.teco, c)
        if n is not None:
            n -= 1
            tags = tag.split (',')
            if not 0 <= n < len (tags):
                return
            tag = tags[n]
        if self.iterstack:
            self.cmdpos = self.iterstack[-1].start
        else:
            self.cmdpos = 0
        self.findtag (tag)

    def p (self, c):
        """P command -- page ahead the specified number of pages
        in the input file, writing to the output file in the process.

        PW command -- write the current buffer to the output file.
        """
        m, n, colon = self.getargsc (c, 1)
        c2 = self.peeknextcmd ().lower ()
        if m is not None or c2 == 'w':
            if c2 == 'w':
                self.nextcmd ()
            if m is not None:
                part = m, n
                repeat = 1
            else:
                part = None
                repeat = n
                if n <= 0:
                    raise IPA (self.teco)
            for i in range (repeat):
                self.buffer.writepage (part)
        else:
            if n <= 0:
                raise IPA (self.teco)
            for i in range (n):
                ret = self.buffer.page ()
            if colon:
                self.setval (ret)
            
    def q (self, c):
        """Q command -- return the numeric value in the specified Q-register.
        If an argument is given, return the ASCII value of the
        character in the text part of the Q-register at the specified
        offset (counting from zero).
        """
        colon = self.colon ()
        n = self.getoptarg (c)
        q = self.qreg ()
        if colon:
            self.clearmods ()
            self.setval (len (q.getstr ()))
        elif n is not None:
            self.clearargs ()
            qstr = q.getstr ()
            if 0 <= n < len (qstr):
                n = ord (qstr[n])
            else:
                n = -1
            self.setval (n)
        else:
            self.clearmods ()
            self.setval (q.getnum ())
        
    def r (self, c):
        """R command -- move backward by the specified number of
        character positions.
        """
        newpos = self.dot - self.getarg (c, 1)
        if 0 <= newpos <= self.end:
            self.buffer.goto (newpos)
        else:
            raise POP (self.teco, c)

    def s (self, c):
        """S command -- search for a string.  If colon modified,
        return -1 if ok, 0 if no match.  If :: modified, it's a
        match operation rather than a search (pointer never moves).
        """
        s = self.strarg (c)
        colons = self.colons
        topiffail = colons < 2
        m, n, colon = self.getargsc (c, 1)
        if not n:
            raise ISA (self.teco)
        if m == 0:
            m = None
            topiffail = False
        if n < 0:
            start, end = 0, self.dot
            if m is not None:
                start = end - abs (m)
        else:
            start, end = self.dot, self.end
            if m is not None:
                end = start + abs (m)
        if colons > 1:
            start = self.dot
            end = start
        nextpage = None
        if c == "n":
            nextpage = self.buffer.page
        elif c == "_":
            nextpage = self.y
        elif c == "e_":
            nextpage = self.ey
        self.search (s, n, start, end, colon, topiffail, nextpage)
        
    echar137 = s              # e_
    n = s
    char137 = s               # _
    
    def t (self, c):
        """T command -- type the specified number of lines.
        """
        m, n = self.teco.lineargs (c)
        sys.stdout.write (printable (self.buf[m:n]))
        sys.stdout.flush ()
        self.screenok = False
        self.clearargs ()
        
    def u (self, c):
        """U command -- set the numeric part of the Q-register
        to the specified value.
        """
        q = self.qreg ()
        q.setnum (self.getarg (c, NAU))
        
    def v (self, c):
        """V command -- display the current line, with n lines to each
        side of it if argument n is supplied, or m before and n after
        if argument pair m,n is given.
        """
        m, n = self.getargs (c, 1)
        start = self.buffer.line (1 - (m or n))
        end = self.buffer.line (n)
        sys.stdout.write (printable (self.buf[start:end]))
        sys.stdout.flush ()
        self.teco.screenok = False

    def w (self, c):
        """W command -- watch the buffer contents.

        If wxPython is available, a wxPython window is opened showing
        the current buffer around dot, which will be updated as the
        buffer changes or dot moves, until further notice.  0W will
        stop the display.

        If wxPython is not available but curses is, the buffer contents
        will be displayed using screen control sequences on the current
        terminal.  It is updated only when another W command is issued.

        Also, in that mode, :W does lots of magical things; refer to
        the manual for all the details.
        """
        m, n, colon = self.getargsc (c)
        if wxpresent:
            if n is None:
                self.teco.startdisplay ()
            elif n == 0:
                self.teco.hidedisplay ()
        elif cursespresent:
            if colon:
                if n is None:
                    n = 0
                if n & -256:
                    # insert until...
                    if not n & 1:
                        self.teco.watch ()
                    term = m and [ m & 255, m >> 8 ]
                    if n & 2:
                        m.append (9)
                    while True:
                        ch = screen.getch ()
                        if ch == 3:
                            if self.etflag & 32768:
                                self.etflag &= -32768
                            else:
                                raise XAB (self.teco)
                        if (n & 64) or \
                               (ch != 9 and ch < 32) or ch > 126 or \
                               (term and ch in term):
                            break
                        c = chr (ch)
                        if n & 4:
                            c = c.upper ()
                        self.buffer.insert (c)
                        if not n & 32:
                            self.teco.watch ()
                    self.setval (ch)
                    return
                if not 0 <= n <= 7:
                    raise ARG (self.teco)
                if m is None:
                    self.setval (self.teco.watchparams[n])
                else:
                    if n:
                        self.teco.watchparams[n] = m
            else:
                if n is None:
                    endwin ()
                else:
                    if n == 0:
                        n = 16
                    if n > 0:
                        self.teco.curline = n
                    else:
                        if n == -1000:
                            self.screenok = True
                        self.teco.watch ()
        else:
            raise ILL (self.teco, c)
        
    def x (self, c):
        """X command -- set the text part of the specified Q-register
        from text in the buffer.  If one numeric argument is present,
        that is a number of lines.  If two arguments are given, it
        is the range of character positions in the buffer.  If colon-
        modified, the new text is appended to the existing Q-register
        contents rather than replacing it.
        """
        colon = self.colon ()
        m, n = self.teco.lineargs (c)
        q = self.qreg ()
        text = self.buf[m:n]
        if colon:
            q.appendstr (text)
        else:
            q.setstr (text)
        self.clearargs ()
        
    def y (self, c = None):
        """Y command -- read the next page.  If the buffer is not
        empty, and there is an output file, refuse the operation unless
        bit 1 is set in ED.
        """
        self.buffer.yank ((self.edflag & 2) == 0)
    
    def z (self, c):
        """Z command -- the number of characters in the buffer, or in
        other words, the character position corresponding to the
        end of the buffer.
        """
        self.setval (self.end)
        
    def char133 (self, c):    # [
        """[ command -- push the specified Q-register onto the
        Q-register stack.
        """
        # We have to make a copy of the Q register so that any later
        # changes to the existing one are not also reflected in the
        # pushed copy.  A shallow copy suffices.
        self.teco.qstack.append (copy.copy (self.qreg ()))

    def char134 (self, c):    # \
        r"""\ command -- number/string conversion.

        If an argument is supplied, convert that according to the
        current radix, and insert it into the buffer.  Note that ^S
        is not updated to reflect that insertion.

        If no argument is present, parse a number from the current
        buffer position according to the current radix, and return that
        number as a result.  Dot is moved across whatever was parsed.
        """
        n = self.getoptarg (c)
        if n is None:
            self.clearmods ()
            if self.radix == 8:
                m = octre.match (self.buf, self.dot)
            elif self.radix == 10:
                m = decre.match (self.buf, self.dot)
            else:
                m = hexre.match (self.buf, self.dot)
            if m is None:
                n = 0
            else:
                n = int (m.group (0), self.radix)
                self.dot = m.end ()
            self.setval (n)
        else:
            self.clearargs ()
            if self.radix == 8:
                s = "%o" % n
            elif self.radix == 10:
                s = "%d" % n
            else:
                s = "%x" % n
            self.buffer.insert (s)

    def char135 (self, c):    # ]
        """] command -- pop the Q-register stack into the specified
        Q-register.
        """
        colon = self.colon ()
        if self.teco.qstack:
            q = self.teco.qstack.pop ()
            self.setqreg (q)
            if colon:
                self.setval (-1)
        elif colon:
            self.nextcmd ()
            self.setval (0)
        else:
            raise PES (self.teco)
        
    def char136 (self, c):    # ^
        """^ command -- take the next character as a control character,
        for example '^S' is the same as 'control-S'.
        """
        self.do (self.makecontrol (self.nextcmd ()))

    def char174 (self, c):    # |
        """| command -- marks the start of the 'else' part of
        a conditional execution block.
        """
        self.skipcond ("'")

class inputstream (object):
    def __init__ (self, teco):
        self.teco = teco
        self.pages = ""
        self.eoflag = -1
        self.ffflag = 0
        self.infile = False

    def open (self, fn, colon):
        fn = os.path.expanduser (fn)
        try:
            infile = open (fn, "rt", encoding = "utf8", errors = "ignore")
            self.teco.lastfilename = fn
        except IOError as err:
            if colon:
                return 0
            if err.errno == 2:
                raise FNF (self.teco, fn)
            else:
                raise FER (self.teco)
        try:
            indata = infile.read ()
        except IOError:
            raise INP (self.teco)
        infile.close ()
        self.pages = indata.split (ff)
        self.infile = True                 # input file is "open"
        self.infn = fn
        self.eoflag = 0
        return -1

    def readpage (self):
        if self.pages:
            ret = self.pages[0].replace (lf, crlf)
            del self.pages[0]
            if len (self.pages):
                self.ffflag = -1
                self.eoflag = 0
            else:
                self.ffflag = 0
                self.eoflag = -1
            return ret, -1
        else:
            self.ffflag = 0
            self.eoflag = -1
            return "", 0
        
class outputstream (object):
    def __init__ (self, teco):
        self.teco = teco
        self.outfile = None

    def open (self, fn, colon, scheck = True):
        if self.outfile:
            raise OFO (self.teco)
        fn = os.path.expanduser (fn)
        fdir = os.path.dirname (os.path.abspath (fn))
        if scheck and not fn.lower ().endswith (".tmp") and os.path.isfile (fn):
            print('%%Superseding existing file "%s"' % fn)
        # Put the tempfile in the output directory so we don't end up
        # with cross-mountpath issues.
        fd, self.tempfn = tempfile.mkstemp (text = True, dir = fdir)
        try:
            self.outfile = open (fd, "wt", encoding = "utf8", errors = "ignore")
            self.teco.lastfilename = fn
        except IOError as err:
            if colon:
                return 0
            raise FER (self.teco)
        self.outfn = fn
        return -1
    
class buffer (object):
    '''This class defines the TECO text buffer, and methods to manipulate
    its contents.
    '''
    def __init__ (self, teco):
        self.text = ""
        self.dot = 0
        self.teco = teco
        self.ebflag = False
        self.inputs = [ None, None ]
        self.istream = 0
        self.outputs = [ None, None ]
        self.ostream = 0

    laststringlen = commonprop ("laststringlen")
    
    def insert (self, text):
        self.text = self.text[:self.dot] + text + self.text[self.dot:]
        self.dot += len (text)
        self.laststringlen = -len (text)

    def delete (self, len):
        self.text = self.text[:self.dot] + self.text[self.dot + len:]

    def goto (self, pos):
        if pos < 0: pos = 0
        if pos > len (self.text): pos = len (self.text)
        self.dot = pos
            
    def _end (self):
        return len (self.text)

    end = property (_end)
    
    def _ffflag (self):
        infile = self.inputs[self.istream]
        if infile:
            return infile.ffflag
        else:
            return 0

    ffflag = property (_ffflag)
    
    def _eoflag (self):
        infile = self.inputs[self.istream]
        if infile:
            return infile.eoflag
        else:
            return -1

    eoflag = property (_eoflag)
    
    def line (self, linecnt):
        pos = self.dot
        if linecnt > 0:
            while linecnt > 0:
                try:
                    pos = self.text.index (lf, pos) + 1
                except ValueError:
                    return len (self.text)
                linecnt -= 1
            return pos
        else:
            while linecnt <= 0:
                try:
                    pos = self.text.rindex (lf, 0, pos)
                except ValueError:
                    return 0
                linecnt += 1
            return pos + 1

    def ea (self):
        self.ostream = 1
        
    def eb (self, fn,colon):
        if self.outputs[self.ostream]:
            raise OFO (self.teco)
        ret = self.er (fn, colon)
        if ret == -1:
            ret = self.ew (fn, colon, False)
            if ret == -1:
                self.ebflag = True
        return ret
    
    def ec (self):
        infile = self.inputs[self.istream]
        outfile = self.outputs[self.ostream]
        if outfile:
            if infile:
                while self.page () < 0:
                    pass
            else:
                self.writepage ()
                self.text = ""
            self.ef ()
        elif self.end:
            raise NFO (self.teco)
        
    def ef (self):
        infile = self.inputs[self.istream]
        self.inputs[self.istream] = None
        outfile = self.outputs[self.ostream]
        if outfile:
            if self.ebflag:
                try:
                    os.remove (infile.infn + '~')
                except:
                    pass
                os.rename (infile.infn, infile.infn + '~')
                self.ebflag = False
            outfile.outfile.close ()
            self.outputs[self.ostream] = None
            os.rename (outfile.tempfn, outfile.outfn)

    def ek (self):
        outfile = self.outputs[self.ostream]
        if outfile:
            outfile.outfile.close ()
            self.outputs[self.ostream] = None
            os.remove (outfile.tempfn)
            self.ebflag = False
            
    def ep (self):
        self.istream = 1
        
    def er (self, fn, colon):
        """ This opens an input file, reads the whole file, and breaks it
        into pages.
        I suppose that isn't really all that elegant, but unless the
        file is humongous, it's fast enough these days, and it produces
        the correct result.
        """
        if not len (fn):
            self.istream = 0
            return True
        if not self.inputs[self.istream]:
            self.inputs[self.istream] = inputstream (self.teco)
        return self.inputs[self.istream].open (fn, colon)
    
    def ew (self, fn, colon, scheck = True):
        """This opens an output file.  It creates the output file using
        a temporary name, in the directory specified.  The actual
        desired name is saved, and will be set when the file is closed.
        """
        if not len (fn):
            self.ostream = 0
            return True
        if not self.outputs[self.ostream]:
            self.outputs[self.ostream] = outputstream (self.teco)
        return self.outputs[self.ostream].open (fn, colon, scheck)
        
    def yank (self, protect = True):
        """Read another page into the text buffer.  If 'protect' is
        True or omitted, the operation is rejected if there is an
        output file and the buffer is non-empty.
        Returns -1 if there was more data to read, 0 if we were
        at end of file already.
        """
        if protect and self.outputs[self.ostream] and self.text:
            raise YCA (self.teco)
        self.text = ""
        ret = self.append ()
        self.goto (0)
        return ret

    def append (self):
        """Append another page to the text buffer.
        """
        infile = self.inputs[self.istream]
        if not infile:
            raise NFI (self.teco)
        newstr, ret = infile.readpage ()
        self.text += newstr
        return ret

    def writepage (self, part = None):
        outfile = self.outputs[self.ostream]
        if not outfile:
            raise NFO (self.teco)
        if part:
            start, end = part
            outfile.outfile.write (self.text[start:end].replace (crlf, lf))
        else:
            outfile.outfile.write (self.text.replace (crlf, lf))
            
    def page (self):
        """Write out the current page, and read the next.
        """
        infile = self.inputs[self.istream]
        outfile = self.outputs[self.ostream]
        self.writepage ()
        if infile and infile.ffflag:
            outfile.outfile.write (ff)
        return self.yank (False)
        
class command_handler (object):
    '''Class for handling TECO input.

    It handles terminal input as well as input from EI files,
    either single characters, or a complete TECO command with
    the usual special character processing.
    '''
    def __init__ (self, teco):
        self.eifile = None
        self.teco = teco

    etflag = commonprop ("et")

    def ei (self, fn, colon = False):
        """EI file opener.

        If the supplied file name does not contain a directory spec,
        we look for the file in several places.  The list of places to
        look is given by environment variable TECO_PATH, if defined,
        or PATH, if that is defined, or else Python's built in
        default path.   The first match is used; if all choices fail
        then the EI fails (with a return status of 0 if colon-modified,
        or error FNF otherwise).
        """
        if fn:
            fn = os.path.expanduser (fn)
            if self.eifile:
                self.eifile.close ()
            f = None
            if not os.path.dirname (fn):
                fn
                for d in (os.environ.get("TECO_PATH",None) or
                          os.environ.get("PATH",None) or
                          os.defpath).split(os.pathsep):
                    realfn = os.path.join (d, fn)
                    try:
                        f = open (realfn, "r", encoding = "utf8",
                                  errors = "ignore")
                        break
                    except IOError as err:
                        if err.errno == 2:
                            pass
                        else:
                            raise FER (self.teco)
            else:
                try:
                    f = open (fn, "r", encoding = "utf8", errors = "ignore")
                    realfn = fn
                except IOError as err:
                    if err.errno == 2:
                        pass
                    else:
                        raise FER (self.teco)
            if f:
                self.eifile = f
            elif colon:
                return 0
            else:
                raise FNF (self.teco, fn)
        else:
            if self.eifile:
                self.eifile.close ()
                self.eifile = None
        return -1

    def getch (self, trap_ctrlc = True):
        if self.eifile:
            try:
                c = self.eifile.read (1)
            except IOError:
                self.eifile = None
                raise INP (self.teco)
            if len (c):
                if c == lf:
                    c = cr
                return c
            self.eifile.close ()
            self.eifile = None
        if screen and self.teco.incurses:
            c = screen.getch ()
            if c < 256:
                c = chr (c)
            else:
                c = '\000'
        else:
            c = getch ()
        if c == ctrlc and trap_ctrlc:
            if self.etflag & 32768:
                self.etflag &= 32767
            else:
                raise XAB (self.teco)
        if c == cr:
            sys.stdout.write (crlf)
        elif c != rubchr:
            sys.stdout.write (printable (c))
        sys.stdout.flush ()
        return c
    
    def teco_cmdstring (self):
        '''Get a command string using the TECO input conventions.
        Text is accumulated until a double escape is seen.  Control/U
        and rubout are processed.  Double control/G exits with a null
        command (which will cause the main loop to prompt again).
        '''
        buf = ""
        bellflag = False
        escflag = False
        immediate = True
        while True:
            c = self.getch (False)
            if not self.eifile:
                # Most special characters are only special if they
                # come from the terminal, not from an EI file.
                if immediate:
                    if c in "\010\012?":
                        print()
                        return c
                    elif c == '*':
                        c = self.getch (False)
                        if c.isalnum ():
                            print()
                            return '*' + c
                        buf = '*'
                    immediate = False
                if c == bell:
                    if bellflag:
                        print()
                        return ""
                    bellflag = True
                elif bellflag:
                    bellflag = False
                    if c == ' ':
                        buf = buf[:-1]
                        try:
                            start = buf.rindex (lf)
                        except ValueError:
                            start = 0
                        print()
                        sys.stdout.write (printable (buf[start:]))
                        sys.stdout.flush ()
                        continue
                    elif c == '*':
                        buf = buf[:-1]
                        print()
                        sys.stdout.write (printable (buf))
                        sys.stdout.flush ()
                        continue
                if c == ctrlu:
                    print()
                    try:
                        ls = buf.rindex (lf)
                        buf = buf[:ls + 1]
                    except ValueError:
                        buf = ""
                    continue
                elif c == rubchr:
                    if len (buf):
                        sys.stdout.write ("\010 \010")
                        if ord (buf[-1]) < 32 and buf[-1] != esc:
                            sys.stdout.write ("\010 \010")
                        buf = buf[:-1]
                        sys.stdout.flush ()
                    continue
            if c == esc:
                buf += c
                if escflag:
                    if not self.eifile:
                        print()
                    return buf
                escflag = True
                continue
            else:
                escflag = False
            if c == cr:
                buf += crlf
            else:
                buf += c

# Here's a rather primitive (but functional) teco command handler.
# This one is used if we can't find a teco.tec anywhere.
defmacro = \
"""0ed 0^x ^d z"e @o/end/' j
::@s/tec/"s 0u1 :@s*/i*"s -1u1 @fr// <::@s/^ea/; @fr//>'
j :@s/^es/"f hk @o/end/' b,.k :@s/=/"f hx1 hk
q1"f @eb/^eq1/ y @o/end/'
@er/^eq1/ y @o/end/'
@fr// .,zx1 @er/^eq1/ b,.x1 @ew/^eq1/ hk y @o/end/'
::@s/mun/"s :@s/^es/"f @^a/?How can I MUNG nothing?
/ ^c' b,.k :@s/,/"s @fr// 1+' 0"e zj' b,.x1 b,.k @ei/^eq1/ @o/end/'
::@s/mak/"f @^a/?Illegal command "/ ht @^a/"
/ ^c' :@s/^es/"f @^a/?How can I MAKE nothing?
/ ^c' b,.k z-4"e ::@s/love/"s @^a/Not war?
/ j'' hx1 hk @ew/^eq1/'
!end!"""

def main ():
    global t
    t = teco ()
    arg0 = os.path.basename (sys.argv[0]).lower ()
    if arg0.endswith (".py"):
        arg0 = arg0[:-3]
    elif arg0.endswith (".pyc"):
        arg0 = arg0[:-4]
    cmdline = " ".join ([ arg0 ] + sys.argv[1:])
    t.buf = cmdline
    if wxpresent:
        # Need to create a new thread for interaction, then this
        # (main) thread will own the window.
        thr = threading.Thread (target = main2)
        thr.start ()
        global display, dsem
        dsem = threading.Semaphore (value = 0)
        # Wait for someone to ask for a display
        dsem.acquire ()
        if exiting:
            return
        # Now start the display
        display = displayApp (t)
        display.start ()
    else:
        main2 ()
        
def main2 ():
    #t.trace = True                             # *** for debug
    if not t.cmdhandler.ei ("teco.tec", True):
        try:
            t.runcommand (defmacro)
        except err as e:
            e.show ()
    t.mainloop ()
        
if __name__ == "__main__":
    main ()
