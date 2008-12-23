#!/usr/bin/env python

from distutils.core import setup

def normalizeWhitespace(s):
    return ' '.join(s.split())

setup(
    name = 'pytvshows',
    version = '0.2+svn',
    description = 'A simple, shell based tvrss.net torrent downloader.',
    author = 'Ben Firshman',
    author_email = 'ben@firshman.co.uk',
    url = 'http://pytvshows.sourceforge.net/',
    long_description = normalizeWhitespace("""pytvshows downloads torrents for 
    TV shows from RSS feeds provided by tvRSS.net. It is designed to be run 
    from cron or a shell for programs like rTorrent. It is based on TVShows 
    (http://tvshows.sourceforge.net/)."""),
    classifiers = [
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: GNU General Public License (GPL)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Topic :: Communications",
        "Topic :: Internet",
        "Topic :: Other/Nonlisted Topic",
        "Environment :: Console",
        ],
    
    scripts = ['scripts/pytvshows',],
    packages = ['pytvshows',],
    )

