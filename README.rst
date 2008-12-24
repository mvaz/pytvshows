=========
PyTVShows
=========

pytvshows downloads torrents for TV shows from RSS feeds provided by 
`tvRSS.net <http://tvrss.net/>`_. It is designed to be run from cron or a shell 
for programs like rTorrent. It is based on `TVShows 
<http://tvshows.sourceforge.net/>`_.

Dependencies
------------

- `Universal Feed Parser 4.1 <http://www.feedparser.org/>`_ (python-feedparser 
  on Debian and Ubuntu)

Installation
------------

To install::

    python setup.py install

Usage
-----

To view available options::

    pytvshows --help

Configuration
-------------

By default, the configuration is saved at ``~/.pytvshows/config``. Unless you 
have configured the state file to be stored elsewhere, make sure you create
this directory and it is writable.

The configuration file is used to tell pytvshows what shows to download and
stores general configuration options. It consists of headings of the exact
tvrss.net names, as well as the ``pytvshows`` heading to store general options. 

The exact name is the name in the tvrss.net URL when viewing the episodes of a 
show.

For example::

    [pytvshows]
    log=~/.pytvshows/pytvshows.log
    output-directory=~/torrents
    [Heroes]
    [Without+a+Trace]
    [Lost]

The general options use the same names as the long command line options.

Here is a sample cron job that will run every half hour::

    19,49 * * * * pytvshows

**IMPORTANT**: Please change the two numbers at the start to something different
that are half an hour apart. We don't want to be hammering tvrss.net's 
servers at a specific time.

Bugs
----

Please report bugs on the `Google Code page <http://code.google.com/p/pytvshows/>`_.

PyTVShows should work on all platforms, but it has only been tested on Linux. At
some point I'll write up how to use it with rTorrent.

Contributions
-------------

Patches are very welcome. Thanks go to:

- `dclist <https://sourceforge.net/users/dclist/>`_
