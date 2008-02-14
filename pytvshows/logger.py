# encoding: utf-8
"""
PyTVShows - Wrapper for logging to add level adjustment

Copyright (C) 2007, Ben Firshman

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""

from logging import *
import math

SORTED_LEVELS = sorted([NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL])
MIN_LEVEL = SORTED_LEVELS[0]
MAX_LEVEL = SORTED_LEVELS[-1]

def __increaseLevel(self, count=1):
    '''Increase level to next greater Python defined log level.
    Maximum Python defined level if none larger.'''
    if count == 0:
        return
    assert(count > 0)
    # FIXME: Do we need to use 'ceil' here?
    self.level = (int(self.level) / 10 + count) * 10
    if self.level > MAX_LEVEL:
        self.level = MAX_LEVEL

def __decreaseLevel(self, count=1):
    '''Decrease level to next lesser Python defined log level.
    Minimum Python defined level if none lesser.'''
    if count == 0:
        return
    assert(count > 0)
    self.level = int(math.ceil(float(self.level) / 10) - count) * 10
    if self.level < MIN_LEVEL:
        self.level = MIN_LEVEL
    
Handler.increaseLevel = __increaseLevel
Handler.decreaseLevel = __decreaseLevel
