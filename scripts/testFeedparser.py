#!/usr/bin/env python
# encoding: utf-8
"""
testFeedparser.py

Created by Miguel Vaz on 2009-07-25.
Copyright (c) 2009 Universidade do Minho. All rights reserved.
"""

import sys
import os
import feedparser


def main():
	d = feedparser.parse("http://www.mininova.org/rss.xml?user=eztv")
	# print d['entries'][0].title
	for entry in d['entries']:
		print entry.title
		# get the season,  episode number, and series 
	


if __name__ == '__main__':
    main()

