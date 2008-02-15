# encoding: utf-8
"""
PyTVShows - Library
http://pytvshows.sourceforge.net/

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

import sys
if not hasattr(sys, "version_info") or sys.version_info < (2,4):
    raise RuntimeError("PyTVShows requires Python 2.4 or later.")

# TODO:
# * Support range of episodes (21-22 for example)
# * Per-show settings such as quality

import pytvshows.bencode as bencode
import pytvshows.logger as logging

import datetime
import feedparser
import operator
import os
import re
import sha
import socket; socket_errors = []
for e in ['error', 'gaierror']:
    if hasattr(socket, e): socket_errors.append(getattr(socket, e))
socket.setdefaulttimeout(15) # Stops ridiculously long hangs
import time
import urllib
import urllib2
import urlparse

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
    'friendly-filenames': False
}

class TorrentError(Exception): pass
class TorrentDownloadError(TorrentError): pass
class TorrentWriteError(TorrentError): pass
class TorrentTrackerError(TorrentError): pass
class TorrentNoScrapeError(TorrentError): pass
class EpisodeError(Exception): pass
class EpisodeNoWorkingTorrentsError(EpisodeError): pass
class EpisodeQualityDelayError(EpisodeError): pass
class ShowError(Exception): pass
class ShowFeedError(ShowError): pass
class ShowFeedNotModifiedError(ShowFeedError): pass
class ShowFeedNoEpisodesError(ShowFeedError): pass
class ShowDetailsError(ShowError): pass

class Torrent(object):
    """A single torrent file for an episode.
    
    Arguments:
    episode - Episode object that the torrent belongs to
    url - URL to the torrent
    quality - Integer quality of episode, as specified in config
    published_time - Publishing time of torrent as a datetime.datetime object
    filename - Filename to save torrent to
    """
    def __init__(self, episode, url, quality, published_time):
        self.episode = episode
        self.url = url
        self.quality = quality # TODO: pass torrent title here and figure this
        self.published_time = published_time
        
        self.dict = None
        self.file = None
        self.tracker_response = None
        
        self._server_filename = None
        
    def download(self):
        """Download this torrent and store the bdecoded dictionary and
        the torrent file in the dict and file attributes respectively.
        The first successful tracker response is stored in the 
        tracker_response attribute.
        
        Returns the torrent as a bdecoded dictionary.
        """
        # TODO: there is no need downloading & checking each time tracker 
        #       fails split this up into downloading torrent and checking 
        #       tracker
        logging.info("Downloading %s..." % self.url)
        request = urllib2.Request(self.url)
        request.add_header('User-Agent', USER_AGENT)
        try:
            f = urllib2.urlopen(request)
        except urllib2.URLError, e:
            if hasattr(e, "reason"):
                raise TorrentDownloadError, "Could not reach server: %s" \
                                            % e.reason
            elif hasattr(e, "code"):
                raise TorrentDownloadError, e
            else:
                raise TorrentDownloadError, "Unknown URLError: %s" % e
        torrent_file = f.read()
        # This is for use in save()
        if "content-disposition" in f.headers.dict:
            r = re.compile('filename="(.+?)"')
            m = r.search(f.headers.dict["content-disposition"])
            if m:
                self._server_filename = m.group(1)
        # Check if torrent is valid
        try:
            torrent_dict = bencode.bdecode(torrent_file)
        except bencode.BTFailure:
            raise TorrentError, "Downloaded file is either " \
                                "corrupted or not a torrent"
        if 'announce' not in torrent_dict.keys():
            raise TorrentError, "Tracker not found in torrent file"
        logging.debug('Torrent "%s" downloaded, %s bytes' 
                        % (torrent_dict['info']['name'], len(torrent_file)))
        # Check if trackers work
        logging.info("Checking tracker (%s)..." % torrent_dict['announce'])
        chosen_tracker = None
        no_scrape_trackers = []
        # Step 1: Check main tracker, make a note if it doesn't support scrape
        try:
            scrape_url = self._get_scrape_url(torrent_dict['announce'])
            try:
                tracker_response = self._check_tracker(scrape_url,
                                            torrent_dict, scrape=True)
                chosen_tracker = torrent_dict['announce']
            except TorrentTrackerError, e:
                logging.info("Tracker error: %s" % e)
        except TorrentNoScrapeError:
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
                    try:
                        scrape_url = self._get_scrape_url(url)
                        try:
                            tracker_response = self._check_tracker(scrape_url, 
                                                torrent_dict, scrape=True)
                            chosen_tracker = url
                            break
                        except TorrentTrackerError, e:
                            logging.info("Tracker error: %s" % e)
                    except TorrentNoScrapeError:
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
            raise TorrentDownloadError, "No working tracker found"
        logging.debug("Working tracker found (%s)" % chosen_tracker)
        self.dict = torrent_dict
        self.file = torrent_file
        self.tracker_response = tracker_response
        return torrent_dict
    
    def save(self, directory=None, filename=None, retry=3):
        """Save torrent to path, or output-directory or output-directory2
        in the configuration if called with no arguments. It is downloaded 
        if it hasn't been already. Returns path that torrent was saved to.
        
        Arguments:
        Directory - Full directory to save torrent under.
                    Default: output-directory from config
        filename - Filename to save torrent as. Default: Automatically
                   generated from episode details.
        retry - Number of times to attempt download. Default: 3
        """
        if directory:
            if not os.path.exists(directory):
                raise TorrentWriteError, "Output directory doesn't exist."
        else:
            if os.path.exists(config['output-directory']):
                directory = config['output-directory']
            elif config['output-directory2'] \
                    and os.path.exists(config['output-directory2']):
                directory = config['output-directory2']
            else:
                raise TorrentWriteError, "Output directory doesn't exist."
        if not self.file:
            if retry > 1:
                self.download_retry(retry)
            else:
                self.download()
        if not filename:
            if not config['friendly-filenames']:
                if self._server_filename:
                    filename = self._server_filename
                else:
                    parsed_url = urlparse.urlparse(self.url)
                    if parsed_url[2][-8:] == ".torrent":
                        try:
                            filename = urllib2.unquote(
                                                parsed_url[2].split("/")[-1])
                        except IndexError:
                            pass
            # friendly-filenames and a fallback
            if not filename:
                filename = "%s.torrent" % str(self.episode)
        filename = self._get_valid_filename(filename)
        path = os.path.join(directory, filename)
        logging.info("Saving torrent to %s..." % path)
        try:
            f = open(path, "w")
        except IOError, e:
            raise TorrentSaveError, "Can't open torrent file for writing: %s"\
                                        % e
        try:
            f.write(self.file)
        finally:
            f.close()
        return path
    
    def download_retry(self, count=3):
        """Same as download(), but retries count times upon failure."""
        i = 1
        while True:
            try:
                return self.download()
            except TorrentDownloadError, e:
                if i < count:
                    logging.info("Download attempt %s of %s failed: %s. "
                                 "Retrying..." % (i, count, e))
                    i+=1
                else:
                    raise

    def _check_tracker(self, url, torrent_dict, scrape=False):
        """Check tracker. url is an announce URL if scrape is False.
        
        Returns tracker response as bedecoded dictionary.
        """
        if not scrape:
            url = self._get_scrape_url(url)
        info_hash = sha.new(bencode.bencode(torrent_dict['info'])).digest()
        req_url = url+"?"+urllib.urlencode({'info_hash': info_hash}) 
        request = urllib2.Request(req_url)
        request.add_header('User-Agent', USER_AGENT)
        try:
            f = urllib2.urlopen(request)
        except urllib2.URLError, e:
            if hasattr(e, "reason"):
                raise TorrentTrackerError, "Could not reach tracker: %s" \
                                            % e.reason
            elif hasattr(e, "code"):
                raise TorrentTrackerError, e
            else:
                raise TorrentTrackerError, "Unknown URLError: %s" % e
        try:
            tracker_response = bencode.bdecode(f.read())
        except bencode.BTFailure:
            raise TorrentTrackerError, "Unrecognised tracker response. " \
                                       "Torrent may not exist on tracker."
        logging.debug("Valid tracker response: %s" % tracker_response)
        if "files" not in tracker_response.keys() \
                or not tracker_response["files"]:
            raise TorrentTrackerError, "Torrent does not exist on tracker."
        return tracker_response

    def _get_scrape_url(self, announce_url):
        """Converts an announce URL to a scrape URL."""
        # http://tech.groups.yahoo.com/group/BitTorrent/message/3275
        l = announce_url.split('/')
        if l[-1] != "announce":
            raise TorrentNoScrapeError
        l[-1] = "scrape"
        return "/".join(l)
    
    def _get_valid_filename(self, s):
        """Returns a valid string for using in a filename.
        Warning: Removes periods (.), so use before adding extension.
        """
        s = s.replace(":", "-") # Make our dates pretty
        return re.sub(r'[^-A-Za-z0-9_\[\]. ]', '', s)
        
class _BaseEpisode(object):
    """The parent class for any episode object. Do not access directly."""
    def __init__(self, show, key):
        self.show = show
        self.key = key
        self.torrents = []
    
    def add_torrent(self, url, quality, published_time):
        """Creates a new torrent and adds it to this episode.
        
        Arguments:
        url - URL to the torrent
        quality - Integer quality of episode, as specified in config
        published_time - Publishing time of torrent as a datetime.datetime
                         object
        """
        torrent = Torrent(
            episode=self,
            url=url,
            quality=quality,
            published_time=published_time)
        self.torrents.append(torrent)
        return torrent
    
    def get_torrent(self, quality=None):
        """Picks a suitable torrent and returns it."""
        if not quality:
            quality = config["quality"]
        # bish, bash, bosh
        #if len(self.torrents) == 1 and self.torrents[0].quality <= quality:
        #    return self.torrents[0]
        # One torrent higher than the quality we want. this is unlikely, but
        # unwanted.
        #elif len(self.torrents) == 1:
        #    raise EpisodeNoWorkingTorrentsError
        
        # Find the highest quality available in the feed. This is to avoid
        # delays trying to find a higher quality torrent if there's really
        # no chance of finding one.
        # The only disadvantage to this method is when a higher quality 
        # episode does actually pop up, we will probably miss the first one.
        best_quality = 0
        for torrent in self.torrents:
            if torrent.quality > best_quality:
                best_quality = torrent.quality
        wanted_quality = min(quality, best_quality)
        shortlist = []
        # First try : download the episodes for which we have the wanted
        # quality
        for torrent in self.torrents:
            if torrent.quality == wanted_quality:
                try:
                    torrent.download_retry()
                    shortlist.append(torrent)
                except TorrentError, e:
                    logging.info("Torrent download failed: %s" % e)
        # Second try : download the episodes for which the quality delay has
        # expired, with the best guess for quality
        if not shortlist:
            min_published_time = sorted(self.torrents,
                key=operator.attrgetter("published_time"))[0].published_time
            d = (datetime.datetime.now() - min_published_time)
            if (d.days * 86400 + d.seconds) > (6 * 3600 * wanted_quality):
                # Pick highest quality that isn't larger than the wanted
                # quality
                max_quality = 0
                for torrent in self.torrents:
                    if torrent.quality > wanted_quality:
                        continue
                    if torrent.quality > max_quality:
                        max_quality = torrent.quality
                for torrent in self.torrents:
                    if torrent.quality == max_quality:
                        try:
                            torrent.download_retry()
                            shortlist.append(torrent)
                        except TorrentError, e:
                            logging.info("Torrent download failed: %s" % e)
            else:
                raise EpisodeQualityDelayError
        if not shortlist:
            raise EpisodeNoWorkingTorrentsError
        # Find best torrent out of our shortlist
        # TODO: check PROPER etc, check seed/leech ratio, etc
        # but for now...
        # This produces a list with the latest first
        return sorted(shortlist,
                      key=operator.attrgetter("published_time"), 
                      reverse=True)[0]
    
    def save(self, quality=None):
        """Picks a suitable torrent for this episode (get_torrent), 
        saves it, then returns path saved to."""
        return self.get_torrent(quality).save()
    
    def __str__(self):
        raise NotImplementedError

class Episode(_BaseEpisode):
    """Represents an episode that can be classified by no other way other
    than the date and time that the torrent was published. By definition, 
    only one torrent is allowed. 
    Main use in show_type: time
    
    Arguments:
    show - Show object that this episode belongs to
    torrent_url - URL to the torrent
    quality - Integer quality of episode, as specified in config
    published_time - Publishing time of torrent as a datetime.datetime object
    """
    def __init__(self, show, torrent_url, quality, published_time):
        super(Episode, self).__init__(show, published_time)
        super(Episode, self).add_torrent(torrent_url, quality, published_time)

    def __str__(self):
        return "%s %s" % (self.show, self.key)
    
    def add_torrent(self, url, quality, published_time):
        raise NotImplementedError, "An Episode object can only have one " \
                                   "torrent."

class EpisodeWithSeasonAndEpisode(_BaseEpisode):
    """Represents an episode classified by a season number and an episode 
    number.
    Main use in show_type: seasonepisode
    For example, "Lost".
    
    Arguments:
    show - Show object that this episode belongs to
    key - (season, episode) tuple
    """ 
    def __str__(self):
        return "%s %02dx%02d" % (self.show, self.key[0], self.key[1])

class EpisodeWithDate(_BaseEpisode):
    """Represents an episode classified by a date.
    Main use in show_type: date. Also used for specials.
    For example, "The Daily Show".
    
    Arguments:
    show - Show object that this episode belongs to
    key - Date of show's airing as a date object
    """
    def __str__(self):
        return "%s %s" % (self.show, self.key)
    
class EpisodeWithTitle(Episode):
    """Represents an episode with a title to identify it. It is an extension
    of Episode, so only one torrent is allowed. The only difference is the 
    title attribute, which should be unique within a show.
    Main use in show_type: title
    For example "Discovery Channel".
    
    Arguments:
    show - Show object that this episode belongs to
    title - The title of this episode
    torrent_url - URL to the torrent
    quality - Integer quality of episode, as specified in config
    published_time - Publishing time of torrent as a datetime.datetime object
    """
    def __init__(self, show, title, torrent_url, quality, published_time):
        super(EpisodeWithTitle, self).__init__(show, torrent_url, quality, 
                                      published_time)
        self.title = title
    
    def __str__(self):
        return "%s - %s" % (self.show, self.title)


class Show(object):
    """Represents a show. For example, "Friends".
    
    Arguments:
    exact_name - Name of show in tvRSS.net URL
    Optional (fetched from tvRSS.net if not specified):
    human_name - A human friendly name for the show
    show_type - seasonepisode, date, title or time
    last_key - Last key for episode downloaded. Type depends on show_type:
                    seasonepisode: (season, episode) tuple
                    date: datetime.date object
                    title: Last title as a string
                    time: datetime.datetime object with 6 arguments
               If a string is supplied, it will be converted to an object
               based on the value of show_type.
    last_special - The publishing date of the last special downloaded as a 
                   datetime.date object. If a string is supplied, it will be 
                   converted. Only applies for show_types seasonepisode, 
                   date and title. A special is an episode that does not
                   fit in to the show_type.
    feed_etag - The last etag receieved from the feed server.
    feed_last_modified - The last last_modified response from the feed server
                         as a datetime.datetime object with 6 arguments. If a
                         string is supplied, it will be converted.
    """
    def __init__(self, exact_name, human_name=None, show_type=None, 
                 last_key=None, last_special=None, feed_etag=None, 
                 feed_last_modified=None):
        self.exact_name = exact_name
        self.human_name = human_name
        self.show_type = show_type
        self.last_key = last_key
        if isinstance(self.last_key, str):
            logging.debug("last_key is a string, converting...")
            if self.show_type == "seasonepisode":
                # convert string to tuple
                self.last_key = \
                    tuple(int(s) for s in self.last_key[1:-1].split(","))
            elif self.show_type == "date":
                # YYYY-MM-DD
                self.last_key = datetime.datetime(*(time.strptime(
                                    self.last_key, "%Y-%m-%d")[0:6])).date()
            elif self.show_type == "time" or self.show_type == "title":
                # YYYY-MM-DD HH:MM:SS
                self.last_key = datetime.datetime(*(time.strptime(
                                    self.last_key, "%Y-%m-%d %H:%M:%S")[0:6]))
        if self.show_type and self.last_key:
            assert (self.show_type == "seasonepisode"
                    and isinstance(self.last_key[0], int) 
                    and isinstance(self.last_key[1], int)) \
                or (self.show_type == "date" 
                    and isinstance(self.last_key, datetime.date)) \
                or (self.show_type == "title"
                    and isinstance(self.last_key, datetime.datetime)) \
                or (self.show_type == "time"
                    and isinstance(self.last_key, datetime.datetime)), \
            "last_key does not correspond to show_type: %s" % last_key
        self.last_special = last_special
        if isinstance(self.last_special, str):
            self.last_special = datetime.datetime(*(time.strptime(
                                self.last_special, "%Y-%m-%d")[0:6])).date()
        if self.last_special:
            assert isinstance(self.last_special,
                datetime.date), "last_special is not a datetime.date object"
        self.feed_etag = feed_etag
        self.feed_last_modified = feed_last_modified
        if isinstance(self.feed_last_modified, str):
            self.feed_last_modified = datetime.datetime(*(time.strptime(
                        self.feed_last_modified, "%Y-%m-%d %H:%M:%S")[0:6]))
        if self.feed_last_modified:
            assert isinstance(self.feed_last_modified,
                datetime.datetime), "feed_last_modified is not a " \
                "datetime.datetime object"
        self.rss = None
        self.episodes = {}
        self.specials = {} # FIXME QUICK!!!: actually download these

    def save_new_episodes(self):
        """Saves new episodes and sets and returns the new last_key."""
        new_episodes = self.get_new_episodes()
        keys = sorted(new_episodes.keys())
        for key in keys:
            try:
                new_episodes[key].save(config["quality"])
                self.last_key = key
            except EpisodeQualityDelayError:
                logging.info("Delaying download of this episode to wait for "
                             "a higher quality to be released.")
            except EpisodeNoWorkingTorrentsError:
                if key == keys[-1]:
                    # TODO: only warn about this once otherwise cron jobs
                    #       will get oh-so-annoying. store in state file
                    #       so we're only bugged once or twice
                    logging.warn("No working torrents found for %s. The "
                                 "download will be attempted again next "
                                 "time PyTVShows is run." 
                                % new_episodes[key])
                else:
                    # TODO: store failed torrents in the state file for
                    #       retrying
                    logging.warn("No working torrents found for %s. You "
                                 "may want to download it manually." 
                                 % new_episodes[key])
        return self.last_key

    def get_new_episodes(self):
        """Returns dictionary of new episodes (ie, where key > last_key).
        Runs get_episodes() if it hasn't been already."""
        if not self.episodes:
            self.get_episodes()
        new_episodes = {}
        for key, episode in self.episodes.items():
            if key > self.last_key:
                new_episodes[key] = episode
        return new_episodes

    def get_episodes(self):
        """Downloads episode information and returns dictionary of episode 
        objects, also stored in the episodes attribute. Updates last_key
        and last_special. Specials are also stored in the attribute 
        specials. Runs get_details() if not details have been provided and 
        it hasn't been run already."""
        if not self.rss:
            self._get_rss_feed()
        if not self.rss['entries']:
            raise ShowFeedNoEpisodesError
        if not self.show_type:
            self.get_details()
        episodes = {}
        last_key = None
        last_special = None
        for episode in self.rss['entries']:
            if self.show_type == 'seasonepisode':
                r = re.compile('Season\s*: ([0-9]*?);')
                se_match = r.search(episode.description)
                r = re.compile('Episode\s*:\ ([0-9]*?)$')
                ep_match = r.search(episode.description)
                if se_match and ep_match:
                    se = (int(se_match.group(1)), int(ep_match.group(1)))
                    if se not in self.episodes:
                        self.episodes[se] = \
                            EpisodeWithSeasonAndEpisode(self, se)
                    self.episodes[se].add_torrent(
                        url = episode.link,
                        quality = self._get_quality(episode.title),
                        published_time = 
                            datetime.datetime(*episode.updated_parsed[:6]))
                    if not last_key or se > last_key:
                        last_key = se
                else:
                    date = self._add_special(episode)
                    if not last_special or date > last_special:
                        last_special = date
            elif self.show_type == 'date':
                r = re.compile('Episode\s*Date:\s*([0-9\-]+)$')
                date_match = r.search(episode.description)
                if date_match:
                    date = datetime.datetime(*(time.strptime(
                        date_match.group(1), "%Y-%m-%d")[0:6])).date()
                    if date not in self.episodes:
                        self.episodes[date] = EpisodeWithDate(self, date)
                    self.episodes[date].add_torrent(
                        url = episode.link,
                        quality = self._get_quality(episode.title),
                        published_time = 
                            datetime.datetime(*episode.updated_parsed[:6]))
                    if not last_key or date > last_key:
                        last_key = date
                else:
                    # er, different date. don't get confused ok?
                    date = self._add_special(episode)
                    if not last_special or date > last_special:
                        last_special = date
            elif self.show_type == "title":
                r = re.compile('Show\s*Title\s*:\s*(.*?);')
                title_match = r.search(episode.description)
                if title_match and "n/a" not in title_match.group(1).lower():
                    title = title_match.group(1)
                    # This is our key for a title type funnily enough.
                    # We can't use the title as the key because they can't
                    # be compared.
                    published_time \
                            = datetime.datetime(* episode.updated_parsed[:6])
                    # BUT! the title needs to be unique too
                    titles = [ep.title for ep in self.episodes.values()]
                    # Thusforth: the wacky title type
                    if published_time not in self.episodes \
                            and title not in titles:
                        self.episodes[published_time] = EpisodeWithTitle(
                            show = self,
                            title = title,
                            torrent_url = episode.link,
                            quality = self._get_quality(episode.title), 
                            published_time = published_time)
                    if not last_key or published_time > last_key:
                        last_key = published_time
                else:
                    date = self._add_special(episode)
                    if not last_special or date > last_special:
                        last_special = date
            elif self.show_type == "time":
                published_time \
                        = datetime.datetime(* episode.updated_parsed[:6])
                # Just forget it if two torrents have exactly the same time
                if published_time not in self.episodes:
                    self.episodes[published_time] = Episode(
                        show = self,
                        torrent_url = episode.link,
                        quality = self._get_quality(episode.title), 
                        published_time = published_time)
                    if not last_key or published_time > last_key:
                        last_key = published_time
                # No specials for time
            else:
                # We really shouldn't get here
                raise ShowError, "Unrecognised show_type"
        if not self.last_key:
            self.last_key = last_key
        if not self.last_special:
            self.last_special = last_special
        return self.episodes
        
    def get_details(self):
        """If details are missing, fetches the human_name and show_type
        from the RSS feed. Returns dictionary with keys huma_name and 
        show_type."""
        if not self.rss:
            self._get_rss_feed()
        logging.info("Getting details for %s..." % self)
        if not self.rss['entries']:
            raise ShowFeedNoEpisodesError
        # Determine human title. We are assuming here that the first episode
        # in the feed has a useful description. This may cause problems
        r = re.compile('Show Name\s*: (.*?);')
        name_match = r.search(self.rss['entries'][0].description)
        if not name_match:
            raise ShowDetailsError, "Could not determine show name for %s." \
                                        % self
        human_name = name_match.group(1)
        # Determine show type
        title_re = re.compile('Show\s*Title\s*:\s*(.*?);')
        season_re = re.compile('Season\s*:\s*([0-9]*?);')
        episode_re = re.compile('Episode\s*:\s*([0-9]*?)$')
        date_re = re.compile('Episode\s*Date:\s*([0-9\-]+)$')
        d = {
            'seasonepisode': 0,
            'date': 0,
            'title': 0
        }
        for episode in self.rss['entries']:
            title_match = title_re.search(episode.description)
            season_match = season_re.search(episode.description)
            episode_match = episode_re.search(episode.description)
            date_match = date_re.search(episode.description)
            if season_match and episode_match:
                d['seasonepisode'] += 1
            elif date_match:
                d['date'] += 1
            elif title_match and title_match.group(1) != 'n/a':
                d['title'] += 1
        # Nothing could be found, fall back to "time" type
        if d.values() == [0, 0, 0]:
            show_type = "time"
        else:
            # Sort keys based on values
            e = d.keys()
            e.sort(cmp=lambda a,b: cmp(d[a], d[b]))
            show_type = e[-1]
        self.human_name = human_name
        self.show_type = show_type
        return {'show_type': show_type, 'human_name': human_name}
    
    def _get_quality(self, s):
        """Given title string, returns quality integer."""
        for key, value in config["quality_matches"].items():
            if key in s:
                return value
        return 0
    
    def _add_special(self, episode):
        """Adds a special episode from feed entry. Returns date of special."""
        date = datetime.datetime(*episode.updated_parsed[:6]).date()
        if date not in self.specials:
            self.specials[date] = EpisodeWithDate(self, date)
        self.specials[date].add_torrent(
            url = episode.link,
            quality = self._get_quality(episode.title),
            published_time = 
                datetime.datetime(*episode.updated_parsed[:6]))
        return date
    
    def _get_rss_feed(self, url=None):
        """Returns the feedparser object and stores it in the rss attribute.
        
        Arguments:
        url - Feed URL to download. Default: "feed" in config.
        """
        if not url:
            url = config['feed'] % self.exact_name
        logging.info("Downloading and processing %s..." % url)
        last_modified = None
        if self.feed_last_modified:
            last_modified = self.feed_last_modified.timetuple()
        r = feedparser.parse(
            url,
            etag = self.feed_etag,
            modified = last_modified,)
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
                raise ShowFeedError, "HTTP error %s: %s" % (http_status, url)
            elif http_status == 304:
                raise ShowFeedNotModifiedError
            elif 'html' in http_headers.get('content-type', 'rss'):
                raise ShowFeedError, "Looks like HTML: %s" % url
            elif http_headers.get('content-length', '1') == '0':
                raise ShowFeedError, "Empty page: %s" % url
            elif hasattr(socket, 'timeout') and exc_type == socket.timeout:
                raise ShowFeedError, "Connection timed out: %s" % url
            elif exc_type == IOError:
                raise ShowFeedError, "%s: %s" % (r.bozo_exception, url)
            elif hasattr(feedparser, 'zlib') \
                    and exc_type == feedparser.zlib.error:
                raise ShowFeedError, "Broken compression: %s" % f.url
            elif exc_type in socket_errors:
                raise ShowFeedError, "%s: %s" \
                                     % (r.bozo_exception.args[1] + f.url)
            elif exc_type == urllib2.URLError:
                if r.bozo_exception.reason.__class__ in socket_errors:
                    exc_reason = r.bozo_exception.reason.args[1]
                else:
                    exc_reason = r.bozo_exception.reason
                raise ShowFeedError, "%s: %s" % (exc_reason, url)
            elif exc_type == KeyboardInterrupt:
                raise r.bozo_exception
            else:
                raise ShowFeedError, "%s: %s" \
                    % (r.get("bozo_exception", "can't process"), f.url)
        self.rss = r
        self.feed_etag = r.etag
        if hasattr(r, "modified"):
            self.feed_last_modified = datetime.datetime(* r.modified[:6])
        else:
            self.feed_last_modified = None
        return r
    
    def __str__(self):
        if self.human_name:
            return self.human_name
        else:
            return self.exact_name
