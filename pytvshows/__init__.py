#!/usr/bin/env python
# encoding: utf-8
"""
PyTVShows - Downloads torrents from tvrss.net based on 
http://tvshows.sourceforge.net/

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

__version__ = '0.2+svn'

USER_AGENT = "PyTVShows/%s +http://pytvshows.sourceforge.net/" % __version__

# TODO:
# * Support range of episodes (21-22 for example)
# * Check more than one episode in Show.get_details() in case of 
#   seasonepisode special

import bencode
import logger as logging

import datetime
import feedparser
import operator
import os
import re
import sha
import socket; socket_errors = []
for e in ['error', 'gaierror']:
    if hasattr(socket, e): socket_errors.append(getattr(socket, e))
socket.setdefaulttimeout(10) # Stops ridiculously long hangs
import sys
import time
import urllib
import urllib2

root_logger = logging.getLogger('')
root_logger.setLevel(logging.DEBUG)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter('%(levelname)-8s: %(message)s')
console.setFormatter(formatter)
root_logger.addHandler(console)

# library config defaults (script config can be found in scripts/pytvshows)
config = {
    'feed': "http://tvrss.net/search/index.php?show_name=%s&show_name_exact" \
            "=true&mode=rss",
    'output-directory': os.path.expanduser("~/"),
    'output-directory2': None,
    'quality_matches': {
        "[HD": 1,
        "[DSRIP": 1,
        "[TVRIP": 1,
        "[PDTV": 1,
        "[DVD": 1,
        "[HR": 2,
        "[720p": 3,
        "[720P": 3,
    },
    'quality': 1,
}

class Episode(object):
    """The parent class for any episode object"""
    def __init__(self, show, torrent_url, published_time, quality):
        self.show = show
        self.torrent_url = torrent_url
        self.published_time = published_time
        self.quality = quality

    def download(self):
        if os.path.exists(config['output-directory']):
            path = os.path.join(config['output-directory'], 
                                self.torrent_file())
        elif config['output-directory2'] \
                and os.path.exists(config['output-directory2']):
            path = os.path.join(config['output-directory2'],
                                self.torrent_file())
        else:
            logging.warn("Output directory doesn't exist.")
        logging.info("Downloading %s..." % self.torrent_url)
        request = urllib2.Request(self.torrent_url)
        request.add_header('User-Agent', USER_AGENT)
        try:
            f = urllib2.urlopen(request)
        except urllib2.URLError, e:
            if hasattr(e, "reason"):
                logging.warn("Could not reach server: %s" % e.reason)
            elif hasattr(e, "code"):
                logging.warn(e)
            else:
                logging.warn("Unknown error: %s", e)
            logging.warn("Downloading torrent failed, skipping.")
            return False
        torrent = f.read()
        # Check if torrent is valid
        try:
            torrent_dict = bencode.bdecode(torrent)
        except bencode.BTFailure:
            logging.warn("Downloaded file is either corrupted or not a " 
                         "torrent, skipping.")
            return False
        if 'announce' not in torrent_dict.keys():
            logging.warn("Tracker not found in torrent file, skipping.")
            return False
        logging.debug('Torrent "%s" downloaded, %s bytes' 
                        % (torrent_dict['info']['name'], len(torrent)))
        # Check if trackers work
        logging.info("Checking tracker (%s)..." % torrent_dict['announce'])
        chosen_tracker = None
        no_scrape_trackers = []
        # Step 1: Check main tracker, make a note if it doesn't support scrape
        scrape_url = self._get_scrape_url(torrent_dict['announce'])
        if scrape_url:
            if self._check_tracker(scrape_url, torrent_dict, scrape=True):
                chosen_tracker = torrent_dict['announce']
        else:
            logging.debug("Tracker does not support scraping.")
            no_scrape_trackers.append(torrent_dict['announce'])
        # Step 2: Check announce-list trackers, again make a note of no scrape
        if not chosen_tracker:
            logging.debug("announce doesn't work, checking announce-list")
            if 'announce-list' not in torrent_dict \
                    or not torrent_dict['announce-list']:
                logging.debug("announce-list key not in torrent")
            else:
                for url in torrent_dict['announce-list']:
                    logging.info("Checking tracker (%s)..." % url)
                    scrape_url = self._get_scrape_url(url)
                    if scrape_url:
                        if self._check_tracker(scrape_url, torrent_dict, 
                                scrape=True):
                            chosen_tracker = url
                            break
                    else:
                        logging.debug("Tracker does not support scraping.")
                        no_scrape_trackers.append(url)
        # Step 3: If these all fail to find a working tracker, use first 
        # tracker without scraping support that can be connected to.
        if not chosen_tracker:
            logging.debug("Falling back to a tracker without scrape support.")
            for url in no_scrape_trackers:
                request = urllib2.Request(req_url)
                request.add_header('User-Agent', USER_AGENT)
                try:
                    f = urllib2.urlopen(request)
                except urllib2.URLError, e:
                    continue
                chosen_tracker = url
                break
        if not chosen_tracker:
            logging.info("No working tracker found, skipping.")
            return False
        logging.info("Working tracker found (%s), saving torrent to %s..."
                        % (chosen_tracker, path))
        try:
            f = open(path, "w")
        except IOError, e:
            logging.warn("Can't open torrent file for writing: %s", e)
            return False
        try:
            f.write(torrent)
        finally:
            f.close()
        return torrent_dict
    
    def download_retry(self, count=3):
        i=0
        while i < count:
            ret = self.download()
            if ret:
                return ret
            logging.info("Torrent download failed, retrying...")
            i+=1
        return False
    
    def _check_tracker(self, url, torrent_dict, scrape=False):
        if not scrape:
            url = self._get_scrape_url(url)
            if not url:
                # Announce URL does not support scrape, give up
                return False
        info_hash = sha.new(bencode.bencode(torrent_dict['info'])).digest()
        req_url = url+"?"+urllib.urlencode({'info_hash': info_hash}) 
        request = urllib2.Request(req_url)
        request.add_header('User-Agent', USER_AGENT)
        try:
            f = urllib2.urlopen(request)
        except urllib2.URLError, e:
            if hasattr(e, "reason"):
                logging.info("Could not reach tracker: %s" % e.reason)
            elif hasattr(e, "code"):
                logging.info(e)
            else:
                logging.info("Unknown error: %s", e)
            return False
        try:
            tracker_response = bencode.bdecode(f.read())
        except bencode.BTFailure:
            logging.info("Unrecognised tracker response. Torrent may not"
                         "exist on tracker.")
            return False
        logging.debug("Valid tracker response: %s" % tracker_response)
        if "files" not in tracker_response.keys() \
                or not tracker_response["files"]:
            logging.info("Torrent does not exist on tracker.")
            return False
        return tracker_response
        
    def _get_scrape_url(self, announce_url):
        """Converts an announce URL to a scrape URL."""
        # http://tech.groups.yahoo.com/group/BitTorrent/message/3275
        l = announce_url.split('/')
        if l[-1] != "announce":
            return False
        l[-1] = "scrape"
        return "/".join(l)
    
    def _clean_name(self, name):
        name = name.replace("/", " ")
        name = name.replace(":", " ")
        name = name.replace(".", " ")
        return name

        
class EpisodeWithSeasonAndEpisode(Episode):
    """
    Represents an episode classified by a season number and an episode 
    number. For example, "Lost"
    """
    def __init__(self, show, torrent_url, published_time, season, episode, 
                    quality):
        super(EpisodeWithSeasonAndEpisode, self).__init__(show, torrent_url,
            published_time, quality)
        self.season = season
        self.episode = episode
    
    def torrent_file(self):
        name = self._clean_name(self.show.human_name)
        return "%s %02dx%02d.torrent" % (name, self.season, self.episode)
        
    def __str__(self):
        return "%s: Season %s, Episode %s, Quality %s" % \
                    (self.show, self.season, self.episode, self.quality)
class EpisodeWithDate(Episode):
    """
    Represents an episode classified by a date.
    For example, "The Daily Show"
    """
    def __init__(self, show, torrent_url, published_time, date, quality):
        super(EpisodeWithDate, self).__init__(show, torrent_url, 
            published_time, quality)
        self.date = date
    
    def torrent_file(self):
        name = self._clean_name(self.show.human_name)
        return "%s %s.torrent" % (name, self.date)
        
    def __str__(self):
        return "%s: %s, Quality %s" % \
                (self.show, self.date, self.quality)
    
class EpisodeWithTitle(Episode):
    """
    Represents an episode with no classification.
    For example "Discovery Channel"
    """
    def __init__(self, show, torrent_url, published_time, title, quality):
        super(EpisodeWithTitle, self).__init__(show, torrent_url, 
            published_time, quality)
        self.title = title
        
    def torrent_file(self):
        name = self._clean_name(self.show.human_name)
        title = self._clean_name(self.title)
        return "%s %s.torrent" % (name, title)
    
    def __str__(self):
        return "%s: %s, Quality %s" % \
                (self.show, self.title, self.quality)
        
class Show(object):
    """Represents a show. For example, "Friends"."""
    def __init__(self, exact_name, args):
        super(Show, self).__init__()
        self.exact_name = exact_name
        self.human_name = args['human_name']
        self.show_type = args['show_type']
        self.season = args['season']
        self.episode = args['episode']
        self.etag = args.get('etag', None)
        self.last_modified = args.get('last_modified', None)
        #YYYY-MM-DD HH:MM:SS
        if args['date']:
            self.date = datetime.datetime(*(time.strptime(
                            args['date'], "%Y-%m-%d")[0:6])).date()
        else:
            self.date = None
        if args['time']:
            self.time = datetime.datetime(*(time.strptime(
                            args['time'], "%Y-%m-%d %H:%M:%S")[0:6]))
        else:
            self.time = None
        self.rss = None
        self._get_rss_feed()
        self.episodes = None
        if not self.show_type or not self.human_name  \
                or (self.show_type == "date" and not self.date) \
                or (self.show_type == "time" and not self.time) \
                or (self.show_type == "seasonepisode" \
                    and (not self.season or not self.episode)):
            self.get_details()
        else:
            # this needs to be done half way through get_details
            self._parse_rss_feed()
        if self.season:
            self.season = int(self.season)
        if self.season:
            self.episode = int(self.episode)
    
    def get_details(self):
        """Tries to get the details for the show from the RSS feed. This 
        should only be run once if the configs are all working OK."""
        logging.info("Getting details for %s..." % self)
        if not self.rss:
            return False
        try:
            episode = self.rss['entries'][0]
        except IndexError:
            logging.warn("There are no episodes in the RSS feed for %s." % \
                self)
            return False
        # Determine human title
        r = re.compile('Show Name\s*: (.*?);')
        name_match = r.search(episode.description)
        if not name_match:
            logging.warn("Could not determine show name for %s." % self)
            return False
        self.human_name = name_match.group(1)
        # Determine show type
        r = re.compile('Show\s*Title\s*:\s*(.*?);')
        title_match = r.search(episode.description)
        r = re.compile('Season\s*:\s*([0-9]*?);')
        season_match = r.search(episode.description)
        r = re.compile('Episode\s*:\s*([0-9]*?)$')
        episode_match = r.search(episode.description)
        r = re.compile('Episode\s*Date:\s*([0-9\-]+)$')
        date_match = r.search(episode.description)
        if season_match and episode_match:
            self.show_type = 'seasonepisode'
        elif date_match:
            self.show_type = 'date'
        elif titlematch and titlematch.group(1) != 'n/a':
            self.show_type = 'time'
        else:
            logging.warn("Could not determine show type for %s." % self)
            return False
        # Determine highest key
        self._parse_rss_feed()
        if not self.episodes:
            return False
        max_key = max(self.episodes.keys())
        if not max_key:
            logging.warn("Could not determine last episode for %s." % self)
            return False
        if self.show_type == 'seasonepisode' \
                and (not self.season or not self.episode):
            (self.season, self.episode) = max_key
            # So we can keep track of specials
            # TODO: need a better way to do this, this is a quick hack. 
            # If there is a special after the latest normal episode, it will
            # download it and we don't want that
            self.time = self.episodes[max_key][0].published_time
        elif self.show_type == 'date' and not self.date:
            self.date = max_key
        elif self.show_type == 'time' and not self.time:
            self.time = max_key

    def get_new_episodes(self):
        """Gets new episodes for the show and updates the key based on what
        show type it is."""
        if self.show_type == 'seasonepisode':
            (self.season, self.episode) = self._get_new_episodes_with_key(
                (self.season, self.episode))
        elif self.show_type == 'date':
            self.date = self._get_new_episodes_with_key(self.date)
        elif self.show_type == 'time':
            self.time = self._get_new_episode_with_key(self.time)
    
    def _get_rss_feed(self):
        """Gets the feedparser object."""
        url = config['feed'] % self.exact_name
        logging.info("Downloading and processing %s..." % url)
        r = feedparser.parse(
            url,
            etag = self.etag,
            modified = self.last_modified,)
            #agent = USER_AGENT,) # FIXME: only one entry is downloaded with 
                                  # this for some reason
        http_status = r.get('status', 200)
        http_headers = r.get('headers', {
          'content-type': 'application/rss+xml', 
          'content-length':'1'})
        exc_type = r.get("bozo_exception", Exception()).__class__
        if not r.entries and not r.get('version', ''):
            msg = None
            if http_status not in [200, 302]: 
                msg = "HTTP error %s: %s" % (http_status, url)
            elif http_status == 304:
                logging.info('Feed not modified since last request')
            elif 'html' in http_headers.get('content-type', 'rss'):
                msg = "Looks like HTML: %s" % url
            elif http_headers.get('content-length', '1') == '0':
                msg = "Empty page: %s" % url
            elif hasattr(socket, 'timeout') and exc_type == socket.timeout:
                msg = "Connection timed out: %s" % url
            elif exc_type == IOError:
                msg = "%s: %s" % (r.bozo_exception, url)
            elif hasattr(feedparser, 'zlib') \
                    and exc_type == feedparser.zlib.error:
                msg = "Broken compression: %s" % f.url
            elif exc_type in socket_errors:
                msg = "%s: %s" % (r.bozo_exception.args[1] + f.url)
            elif exc_type == urllib2.URLError:
                if r.bozo_exception.reason.__class__ in socket_errors:
                    exc_reason = r.bozo_exception.reason.args[1]
                else:
                    exc_reason = r.bozo_exception.reason
                msg = "%s: %s" % (exc_reason, url)
            elif exc_type == KeyboardInterrupt:
                raise r.bozo_exception
            else:
                msg = "%s: %s" % (r.get("bozo_exception", "can't process"),
                                  f.url)
            if msg:
                logging.warn("Can't download feed: %s" % msg)
            return False
        self.rss = r
        self.etag = r.etag
        self.last_modified = r.get('modified', None)
        return r
    
    def _parse_rss_feed(self):
        if not self.rss:
            return False
        episodes = {}
        for episode in self.rss['entries']:
            if self.show_type == 'seasonepisode':
                r = re.compile('Season\s*: ([0-9]*?);')
                season_match = r.search(episode.description)
                r = re.compile('Episode\s*:\ ([0-9]*?)$')
                episode_match = r.search(episode.description)
                if not season_match or not episode_match:
                    # This might be a special with a title
                    r = re.compile('Show\s*Title\s*:\s*(.*?);')
                    title_match = r.search(episode.description)
                    if title_match and title_match.group(1) != 'n/a' \
                                        and title_match.group(1) != '':
                        title = title_match.group(1)
                        logging.info("Found episode with title %s and no " \
                            "season or episode in seasonepisode show." % title)
                        quality = 0
                        for key, value in config["quality_matches"].items():
                            if key in episode.title:
                                quality = value
                                break
                        date = datetime.datetime(* episode.updated_parsed[:6])
                        obj = EpisodeWithTitle(
                            self,
                            episode.link,
                            date,
                            title,
                            quality)
                        last_key = 0
                        for key in episodes.keys():
                            if key[0] == 0 and key[1] > last_key:
                                last_key = key[1]
                        episodes[0, last_key] = [obj]
                    else:
                        logging.info('Could not match season and/or ' \
                            'episode in %s' % episode.description)
                else:
                    quality = 0
                    for key, value in config["quality_matches"].items():
                        if key in episode.title:
                            quality = value
                            break
                    season_num = int(season_match.group(1))
                    episode_num = int(episode_match.group(1))
                    if season_num != 0 and episode_num != 0:
                        obj = EpisodeWithSeasonAndEpisode(
                            self,
                            episode.link,
                            datetime.datetime(* episode.updated_parsed[:6]),
                            season_num,
                            episode_num,
                            quality)
                        try:
                            episodes[season_num, episode_num].append(obj)
                        except KeyError:
                            episodes[season_num, episode_num] = [obj]
                    else:
                        logging.debug('Season or episode number is 0 in %s' \
                                % episode.description)
            elif self.show_type == 'date':
                r = re.compile('Episode\s*Date:\s*([0-9\-]+)$')
                date_match = r.search(episode.description)
                if not date_match:
                    logging.info('Could not match date in %s' % \
                        episode.description)
                else:
                    quality = 0
                    for key, value in config["quality_matches"].items():
                        if key in episode.title:
                            quality = value
                            break
                    date = datetime.datetime(*(time.strptime(
                        date_match.group(1), "%Y-%m-%d")[0:6])).date()
                    obj = EpisodeWithDate(
                        self,
                        episode.link,
                        datetime.datetime(* episode.updated_parsed[:6]),
                        date,
                        quality)
                    try:
                        episodes[date].append(obj)
                    except KeyError:
                        episodes[date] = [obj]
            elif self.show_type == 'time':
                r = re.compile('Show\s*Title\s*:\s*(.*?);')
                title_match = r.search(episode.description)
                if not title_match:
                    logging.info('Could not match title in %s' % \
                                episode.description)
                    title = ""
                else:
                    title = title_match.group(1)
                quality = 0
                for key, value in config["quality_matches"].items():
                    if key in episode.title:
                        quality = value
                        break
                date = datetime.datetime(* episode.updated_parsed[:6])
                obj = EpisodeWithTitle(
                    self,
                    episode.link,
                    date,
                    title,
                    quality)
                try:
                    episodes[date].append(obj)
                except KeyError:
                    episodes[date] = [obj]
        self.episodes = episodes
        return episodes

    def _get_new_episodes_with_key(self, min_key):
        downloaded_episode_keys = []
        if not self.episodes:
            return min_key
        episodes = self.episodes # so we can fuck with it
        # What's the best quality available for the last 7 episodes?
        best_quality = 0
        i = 0
        done = False
        for ep_set in episodes.values():
            for ep in ep_set:
                if ep.quality > best_quality:
                    best_quality = ep.quality
                i += 1
        wanted_quality = min(config["quality"], best_quality)
        # Only get unseen episodes
        # Check seasonepisode specials
        last_time = None
        if self.show_type == 'seasonepisode' and (0, 0) in episodes.keys():
            last_time = None
            for key in episodes.keys():
                if key[0] == 0:
                    if last_time is None \
                            or episodes[key][0].published_time > last_time:
                        last_time = episodes[key][0].published_time
                    if self.time \
                            and episodes[key][0].published_time <= self.time:
                        del episodes[key]
            if last_time:
                self.time = last_time
        # Check normal episodes
        for key in episodes.keys():
            if (self.show_type != 'seasonepisode' or key[0] != 0) \
                    and key <= min_key:
                del episodes[key]
        # First try : download the episodes for which we have the wanted
        # quality
        for key, ep_set in episodes.items():
            for ep in ep_set:
                if ep.quality == wanted_quality:
                    logging.info("Downloading %s..." % ep)
                    if ep.download_retry():
                        downloaded_episode_keys.append(key)
                        break
        # Second try : download the episodes for which the quality delay has
        # expired, with the best guess for quality
        for key, ep_set in episodes.items():
            if key not in downloaded_episode_keys:
                ep_set.sort(key=operator.attrgetter("published_time"))
                min_published_time = ep_set[0].published_time
                d = (datetime.datetime.now() - min_published_time)
                if (d.days*86400 + d.seconds) > 6*3600*wanted_quality:
                    # Try to match wanted quality
                    ep_set.sort(key=operator.attrgetter("quality"))
                    episode = None
                    for ep in ep_set:
                        if ep.quality > wanted_quality and (not episode 
                                or ep.quality > episode.quality):
                            episode = ep
                    if not episode:
                        episode = ep_set[0]
                    logging.info("Downloading %s..." % episode)
                    if episode.download_retry():
                        downloaded_episode_keys.append(key)
        if len(downloaded_episode_keys) > 0:
            downloaded_episode_keys.sort()
            if self.show_type == 'seasonepisode' \
                    and downloaded_episode_keys[-1:][0][0] == 0:
                return min_key
            return downloaded_episode_keys[-1:][0]
        return min_key
    
    def __str__(self):
        if self.human_name:
            return self.human_name
        else:
            return self.exact_name

