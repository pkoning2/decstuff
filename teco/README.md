# TECO in Python

This is an implementation of TECO in Python 3.  I originally wrote it
as a programming language learning exercise, so it's not really
polished, but it is functional.  Since it uses Python 3, it has the
rather unusual property of supporting Unicode directly.

Contents:
* teco.py -- the program.  It supports a "GT40" style via wxPython, if
installed.   "Curses" support (for ANSI terminals) is not yet
operational.
* bmp.tec -- a sample TECO macro showing Unicode support.  It fills
the buffer with all the characters of the Unicode Basic Multinational
Plane.
