from __future__ import division

import re
import os
import sys
import urllib2
import socket
import urlparse
import bz2
import tarfile
from HTMLParser import HTMLParser
from datetime import datetime
import time
import traceback

import xbmc, xbmcgui, xbmcaddon

__scriptid__ = 'script.openelec.devupdate'
__addon__ = xbmcaddon.Addon(__scriptid__)

CURRENT_BUILD = int(re.search('-r(\d+)', open('/etc/version').read()).group(1))
ARCH = open('/etc/arch').read().rstrip()

HEADERS={'User-agent' : "Mozilla/5.0"}

HOME = os.path.expanduser('~')
UPDATE_DIR = os.path.join(HOME, '.update')
UPDATE_FILES = ('SYSTEM', 'SYSTEM.md5',
                'KERNEL', 'KERNEL.md5')
UPDATE_PATHS = (os.path.join(UPDATE_DIR, file) for file in UPDATE_FILES)


def size_fmt(num):
    for s, f in (('bytes', '{0:d}'), ('KB', '{0:.1f)'), ('MB', '{0:.1f}')):
        if num < 1024.0:
            return (f + " {1}").format(num, s)
        num /= 1024.0


def log(txt, level=xbmc.LOGDEBUG):
    if not (__addon__.getSetting('debug') == 'false' and level == xbmc.LOGDEBUG):
        msg = '{0} v{1}: {2}'.format(__addon__.getAddonInfo('name'),
                                     __addon__.getAddonInfo('version'), txt)
        xbmc.log(msg, level)
        
def log_exception():
    log("".join(traceback.format_exception(*sys.exc_info())), xbmc.LOGERROR)
        
def check_url(url, msg="URL not found."):
    xbmcgui.Dialog().ok("URL Error", msg, url,
                        "Please check the URL in the addon settings.")
    __addon__.openSettings()
    
def url_error(url, msg):
    log_exception()
    xbmcgui.Dialog().ok("URL Error", msg, url, 
                        "Please check the XBMC log file.")
    
def write_error(path, msg):
    log_exception()
    xbmcgui.Dialog().ok("Write Error", msg, path,
                        "Check the download directory in the addon settings.")
    __addon__.openSettings()

class Canceled(Exception):
    pass

class WriteError(IOError):
    pass
        

class BuildLink(object):
    """Holds information about an OpenELEC build,
       including how to sort and print them."""

    def __init__(self, baseurl, link, build_date, revision):
        scheme, netloc, path = urlparse.urlparse(link)[:3]
        if not scheme:
            self.filename = link
            # Construct the full url
            self.url = urlparse.urljoin(baseurl, link)
        else:
            if netloc == "www.dropbox.com": 
                link = urlparse.urlunparse((scheme, "dl.dropbox.com", path, None, None, None))
            self.url = link
            # Extract the file name part
            self.filename = os.path.basename(link)
        
        try:
            self.build_date = datetime.strptime(build_date, '%Y%m%d%H%M%S')
        except TypeError:
            # Work around an issue with datetime.strptime when the script is run a second time.
            self.build_date = datetime(*(time.strptime(build_date, '%Y%m%d%H%M%S')[0:6]))
        self.revision = int(revision)
        
    def __eq__(self, other):
        return (self.build_date == other.build_date and
                self.revision == other.revision)

    def __hash__(self):
        return hash((self.revision, self.build_date))

    def __lt__(self, other):
        return self.build_date < other.build_date

    def __str__(self):
        return '{0} ({1}) {2}'.format(self.revision,
                                      self.build_date.strftime('%d %b %y'),
                                      '*' * (self.revision == CURRENT_BUILD))


class BuildLinkExtractor(HTMLParser):
    """Class to extract all the build links from the specified URL"""

    BUILD_RE = re.compile(".*OpenELEC-.*{0}-devel-(\d+)-r(\d+).tar.bz2".format(ARCH))

    def __init__(self, url):
        HTMLParser.__init__(self)
  
        req = urllib2.Request(url, None, HEADERS)
        self.response = urllib2.urlopen(req)
        self.html = self.response.read()
        self.url = url
        
        self.links = []

    def get_links(self):
        self.feed(self.html)
        # Remove duplicates and sort so that the most recent build is first.
        return list(sorted(set(self.links), reverse=True))

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for attr, value in attrs:
                if attr == 'href':
                    m = self.BUILD_RE.match(value)
                    if m:
                        self.links.append(BuildLink(self.url,
                                                    value,
                                                    *m.groups()))

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.response.close()


class FileProgress(xbmcgui.DialogProgress):
    """Extends DialogProgress as a context manager to
       handle the file progress"""

    BLOCK_SIZE = 131072

    def __init__(self, heading, infile, outpath, size):
        xbmcgui.DialogProgress.__init__(self)
        self.create(heading, outpath, size_fmt(size))
        self._size = size
        self._in_f = infile
        try:
            self._out_f = open(outpath, 'wb')
        except IOError as e:
            raise WriteError(e)
        self._outpath = outpath
        self._done = 0
 
    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self._in_f.close()
        self._out_f.close()
        self.close()

        # If an exception occurred remove the incomplete file.
        if type is not None:
            os.remove(self._outpath)

    def start(self):
        while self._done < self._size:
            if self.iscanceled():
                raise Canceled
            data = self._read()
            try:
                self._out_f.write(data)
            except IOError as e:
                raise WriteError(e)
            percent = int(self._done * 100 / self._size)
            self.update(percent)

    def _getdata(self):
        return self._in_f.read(self.BLOCK_SIZE)

    def _read(self):
        data = self._getdata()
        self._done += len(data)
        return data


class DecompressProgress(FileProgress):
    decompressor = bz2.BZ2Decompressor()
    def _read(self):
        data = self.decompressor.decompress(self._getdata())
        self._done = self._in_f.tell()
        return data


def main():
    # Move to the download directory.
    dir = __addon__.getSetting('tmp_dir')
    if not os.path.isdir(dir):
        xbmcgui.Dialog().ok("Directory Error", dir,
                            "Check the download directory in the addon settings.")
        __addon__.openSettings()
        return
    os.chdir(dir)
    log("chdir to " + dir)

    # Get the url from the settings.
    url = __addon__.getSetting('url_list')
    if url == "Other":
        url = __addon__.getSetting('custom_url')
        scheme, netloc, path = urlparse.urlparse(url)[:3]
        if not (scheme and netloc):
            check_url(url, "Invalid URL")
            return
    if not url.endswith('/'):
        url += '/'
    
    # Add the subdirectory.
    url = urlparse.urljoin(url, __addon__.getSetting('subdir'))
    if not url.endswith('/'):
        url += '/'

    log("URL = " + url)    

    try:
        # Get the list of build links.
        with BuildLinkExtractor(url) as extractor:
            links = extractor.get_links()
    except urllib2.HTTPError as e:
        if e.code == 404:
            check_url(e.geturl())
        else:
            url_error(e.geturl(), str(e))
        return
    except urllib2.URLError as e:
        url_error(url, str(e))
        return
            
    if not links:
        check_url(url, "No builds were found for {0}.".format(ARCH))
        return

    # Ask which build to install.
    i = xbmcgui.Dialog().select("Select a build to install (* = currently installed)",
                                [str(r) for r in links])
    if i == -1:
        return
    selected_build = links[i]
    log("Selected build " + str(selected_build))

    # Confirm the update.
    msg = " from build {0} to build {1}?".format(CURRENT_BUILD,
                                                 selected_build.revision)
    if CURRENT_BUILD > selected_build.revision:
        args = ("Confirm downgrade", "Downgrade" + msg)
    elif CURRENT_BUILD < selected_build.revision:
        args = ("Confirm upgrade", "Upgrade" + msg)
    elif CURRENT_BUILD == selected_build.revision:
        args = ("Confirm install",
                "The selected build ({0}) is already installed.".format(selected_build.revision),
                "Continue?")
    if not xbmcgui.Dialog().yesno(*args):
        return

    # Get the file names.
    bz2_name = selected_build.filename
    tar_name, ext = os.path.splitext(bz2_name)

    # Download the build bz2 file and uncompress it if the tar file does not already exist.
    if not os.path.isfile(tar_name):
        req = urllib2.Request(selected_build.url, None, HEADERS)

        try:
            rf = urllib2.urlopen(req)
            log("Opened url " + selected_build.url)
            bz2_size = int(rf.headers.getheader('Content-Length'))
            log("Size of file = " + size_fmt(bz2_size))

            if (os.path.isfile(bz2_name) and
                os.path.getsize(bz2_name) == bz2_size):
                # Skip the download if the file exists with the correct size.
                log("Skipping download")
                pass
            else:
                # Do the download
                log("Starting download of " + selected_build.url)
                with FileProgress("Downloading", rf, bz2_name, bz2_size) as progress:
                    progress.start()
                log("Completed download of " + selected_build.url)   
        except Canceled:
            return
        except (urllib2.HTTPError, socket.error) as e:
            url_error(e.geturl(), str(e))
            return
        except WriteError as e:
            write_error(os.path.join(dir, bz2_name), str(e))
            return


        try:
            # Do the decompression.
            bf = open(bz2_name, 'rb')
            log("Starting decompression of " + bz2_name)
            with DecompressProgress("Decompressing", bf, tar_name, bz2_size) as progress:
                progress.start()
            log("Completed decompression of " + bz2_name)
        except Canceled:
            return
        except WriteError as e:
            write_error(os.path.join(dir, tar_name), str(e))
            return
    else:
        log("Skipping download and decompression")


    tf = tarfile.open(tar_name, 'r')
    log("Starting extraction from tar file " + tar_name)
    
    # Create the .update directory if necessary.
    if not os.path.exists(UPDATE_DIR):
        os.mkdir(UPDATE_DIR)
    
    # Extract the update files from the tar file to the .update directory.
    tar_members = (m for m in tf.getmembers() if os.path.basename(m.name) in UPDATE_FILES)
    for member in tar_members:
        ti = tf.extractfile(member)
        outfile = os.path.join(UPDATE_DIR, os.path.basename(member.name))
        try:
            with FileProgress("Extracting", ti, outfile, ti.size) as progress:
                progress.start()
            log("Extracted " + outfile)
        except Canceled:
            # Remove all the update files.
            try:
                for file in UPDATE_PATHS:
                    os.remove(file)
            except OSError:
                pass
            return
        except WriteError as e:
            write_error(outfile, str(e))
            return

    tf.close()

    # Clean up the temporary files.
    try:
        os.remove(bz2_name)
        if __addon__.getSetting('keep_tar') == "false":
            os.remove(tar_name)
    except OSError:
        pass

    if xbmcgui.Dialog().yesno("Confirm reboot", "Reboot now to install the update?"):
        xbmc.restart()
    else:
        xbmcgui.Dialog().ok("Info", "The update will be installed on the next reboot.")


main()
    
    

