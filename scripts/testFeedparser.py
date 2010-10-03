#!/usr/bin/env python
# encoding: utf-8
"""
testFeedparser.py

Created by Miguel Vaz on 2009-07-25.
Copyright (c) 2009 Universidade do Minho. All rights reserved.
"""

import sys
import os, re
import feedparser
import pprint

url = "http://showrss.karmorra.info/rss.php?user_id=38823&hd=null&proper=null&namespaces=true"

entry_expression = re.compile( r'<strong>New standard torrent for (?P<name>.*?):</strong> <strong>(.*?)</strong>\s*(?P<episode>.*?). Torrent link: <a href=\"(?P<url>.*?)\">.*?</a>', re.U | re.I)

def extract_episode_details(rss_entry):
    output = dict()
    dd = entry_expression.match( rss_entry["summary_detail"]["value"] )
    a = re.search(r'\s*(\d+)x(\d+)', dd.group("episode"), re.I | re.U) 
    output["season"]  = int(a.group(1))
    output["episode"] = int(a.group(2))
    output["name"] = dd.group("name")
    output["url"]  = dd.group("url")
    return output

def main():
    d = feedparser.parse(url)
    #pp = pprint.PrettyPrinter(indent=4)
    #pp.pprint(d)
    for entry in d['entries']:
        entry_details = extract_episode_details( entry )
	# check for current details
	# try to download



if __name__ == '__main__':
    main()

