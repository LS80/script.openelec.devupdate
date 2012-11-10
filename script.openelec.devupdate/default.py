import os
import sys
import urllib2
import socket
import urlparse
import tarfile
import traceback

import xbmc, xbmcgui, xbmcaddon

from constants import CURRENT_BUILD, ARCH, HEADERS
from script_exceptions import Canceled, WriteError
from utils import size_fmt
from builds import BuildLinkExtractor
from progress import FileProgress, DecompressProgress

__scriptid__ = 'script.openelec.devupdate'
__addon__ = xbmcaddon.Addon(__scriptid__)

HOME = os.path.expanduser('~')
UPDATE_DIR = os.path.join(HOME, '.update')
UPDATE_FILES = ('SYSTEM', 'SYSTEM.md5',
                'KERNEL', 'KERNEL.md5')
UPDATE_PATHS = (os.path.join(UPDATE_DIR, file) for file in UPDATE_FILES)

URLS = {"Official":
            "http://sources.openelec.tv/tmp/image",
        "Chris Swan (RPi)":
            "http://openelec.thestateofme.com",
        "vicbitter (ION)":
            "https://www.dropbox.com/sh/crtpgonwqdc4k2n/82ivuohfSs",
        "incubus (Xtreamer Ultra)":
            "https://www.dropbox.com/sh/gnmr4ee19wi3a1y/W5-9rkJT4y"}


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


def main():
    # Check if the update files are already in place.
    if all(os.path.isfile(f) for f in UPDATE_PATHS):
        if xbmcgui.Dialog().yesno("Confirm reboot",
                                  "The update files are already in place.",
                                  "Reboot now to install the update",
                                  "or continue to select another build.",
                                  "Continue",
                                  "Reboot"):
            xbmc.restart()

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
    source = __addon__.getSetting('source')
    if source == "Other":
        url = __addon__.getSetting('custom_url')
        scheme, netloc, path = urlparse.urlparse(url)[:3]
        if not (scheme and netloc):
            check_url(url, "Invalid URL")
            return
    else:
        url = URLS[source]
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
            url_error(selected_build.url, str(e))
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

    if xbmcgui.Dialog().yesno("Confirm reboot",
                              "Reboot now to install build {0}?"
                              .format(selected_build.revision)):
        xbmc.restart()
    else:
        xbmc.executebuiltin("Notification(OpenELEC Dev Update, Build {0} will install "
                            "on the next reboot., 10000)".format(selected_build.revision))


main()
    
    

