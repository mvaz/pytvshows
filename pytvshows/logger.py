# encoding: utf-8
"""
PyTVShows - Wrapper for logging to add level adjustment
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
