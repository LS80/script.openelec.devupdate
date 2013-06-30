from __future__ import division

import os
import sys

import xbmc, xbmcgui, xbmcaddon


def log(txt, level=xbmc.LOGDEBUG):
    
    if not (__addon__.getSetting('debug') == 'false' and level == xbmc.LOGDEBUG):
        msg = '{} v{}: {}'.format(__addon__.getAddonInfo('name'),
                                  __addon__.getAddonInfo('version'), txt)
        xbmc.log(msg, level)
        
def log_exception():
    import traceback
    log("".join(traceback.format_exception(*sys.exc_info())), xbmc.LOGERROR)
        
def bad_url(url, msg="URL not found."):
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
    
def remove_update_files():
    for f in UPDATE_PATHS:
        try:
            os.remove(f)
        except OSError:
            pass
        else:
            log("Removed " + f)
            
def md5sum_verified(md5sum_compare, path):
    import hashlib
    
    progress = xbmcgui.DialogProgress()
    progress.create("Verifying", " ", "Verifying {} md5".format(path), " ")
    
    BLOCK_SIZE = 8192
    
    hasher = hashlib.md5()
    f = open(path)
    
    done = 0
    size = os.path.getsize(path)
    while done < size:
        if progress.iscanceled():
            progress.close()
            return True
        data = f.read(BLOCK_SIZE)
        done += len(data)
        hasher.update(data)
        percent = int(done * 100 / size)
        progress.update(percent)
    progress.close()
        
    md5sum = hasher.hexdigest()
    log("{} md5 hash = {}".format(path, md5sum))
    return md5sum == md5sum_compare


def check_update_files():
    # Check if the update files are already in place.
    if all(os.path.isfile(f) for f in UPDATE_PATHS):
        if xbmcgui.Dialog().yesno("Confirm reboot",
                                  "The update files are already in place.",
                                  "Reboot now to install the update",
                                  "or continue to select another build.",
                                  "Continue",
                                  "Reboot"):
            xbmc.restart()


def cd_tmp_dir():
    # Move to the download directory.
    if not os.path.isdir(tmp_dir):
        xbmcgui.Dialog().ok("Directory Error", "{} does not exist.".format(tmp_dir),
                            "Check the download directory in the addon settings.")
        __addon__.openSettings()
        sys.exit(1)
    os.chdir(tmp_dir)
    log("chdir to " +  tmp_dir)
    
    
class BuildList():

    def create(self):
        import urllib2
        import urlparse
        
        from lib import constants
        from lib import builds
        
        subdir = __addon__.getSetting('subdir')
    
        # Get the url from the settings.
        source = __addon__.getSetting('source')
        log("Source = " +  source)
        if source == "Other":
            # Custom URL
            url = __addon__.getSetting('custom_url')
            scheme, netloc = urlparse.urlparse(url)[:2]
            if not (scheme and netloc):
                bad_url(url, "Invalid URL")
                sys.exit(1)
            
            build_url = builds.BuildsURL(url, subdir)
        else:
            # Defined URL
            build_url = builds.URLS[source]
            url = build_url.url
        
        log("Full URL = " + url)
    
        try:
            # Get the list of build links.
            with build_url.extractor() as parser:
                links = sorted(parser.get_links(), reverse=True)
        except urllib2.HTTPError as e:
            if e.code == 404:
                bad_url(e.geturl())
            else:
                url_error(e.geturl(), str(e))
            sys.exit(1)
        except urllib2.URLError as e:
            url_error(url, str(e))
            sys.exit(1)
                
        if not links:
            bad_url(url, "No builds were found for {}.".format(constants.ARCH))
            sys.exit(1)
            
        return links
        
    def __enter__(self):
        xbmc.executebuiltin("ActivateWindow(busydialog)")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        xbmc.executebuiltin("Dialog.Close(busydialog)")


def select_build(links):
    from lib.builds import INSTALLED_BUILD

    # Ask which build to install.
    i = xbmcgui.Dialog().select("Select a build to install (* = currently installed)",
                                [str(r) + ' *'*(r == INSTALLED_BUILD) for r in links])
    if i == -1:
        sys.exit(0)
    selected_build = links[i]
    log("Selected build " + str(selected_build))

    # Confirm the update.
    msg = " {} -> {}?".format(INSTALLED_BUILD, selected_build)
    if selected_build < INSTALLED_BUILD:
        args = ("Confirm downgrade", " ", "Downgrade" + msg)
    elif selected_build > INSTALLED_BUILD:
        args = ("Confirm upgrade", " ", "Upgrade" + msg)
    else:
        args = ("Confirm install",
                "Build {} is already installed.".format(selected_build),
                "Continue?")
    if not xbmcgui.Dialog().yesno(*args):
        sys.exit(0)
        
    return selected_build


def download(selected_build):
    import urllib2
    import socket
    import tarfile
    
    from lib import constants
    from lib import progress
    from lib import utils
    from lib import script_exceptions

    # Get the file names.
    filename = selected_build.filename
    name, ext = os.path.splitext(filename)
    if ext == '.tar':
        tar_name = filename
    else:
        tar_name = name

    # Download the build file if we don't already have the tar file.
    if not os.path.isfile(tar_name):
        log("Download URL = " + selected_build.url)
        req = urllib2.Request(selected_build.url, None, constants.HEADERS)

        try:
            rf = urllib2.urlopen(req)
            log("Opened URL " + selected_build.url)
            bz2_size = int(rf.headers.getheader('Content-Length'))
            log("Size of file = " + utils.size_fmt(bz2_size))

            if (os.path.isfile(filename) and
                os.path.getsize(filename) == bz2_size):
                # Skip the download if the file exists with the correct size.
                log("Skipping download")
                pass
            else:
                # Do the download
                log("Starting download of " + selected_build.url)
                with progress.FileProgress("Downloading", rf, filename, bz2_size) as downloader:
                    downloader.start()
                log("Completed download of " + selected_build.url)   
        except script_exceptions.Canceled:
            sys.exit(0)
        except (urllib2.HTTPError, socket.error) as e:
            url_error(selected_build.url, str(e))
            sys.exit(1)
        except script_exceptions.WriteError as e:
            write_error(os.path.join(tmp_dir, filename), str(e))
            sys.exit(1)


        # Do the decompression if necessary.
        if ext == '.bz2':
            try:
                bf = open(filename, 'rb')
                log("Starting decompression of " + filename)
                with progress.DecompressProgress("Decompressing", bf, tar_name, bz2_size) as decompressor:
                    decompressor.start()
                log("Completed decompression of " + filename)
            except script_exceptions.Canceled:
                sys.exit(0)
            except script_exceptions.WriteError as e:
                write_error(os.path.join(tmp_dir, tar_name), str(e))
                sys.exit(1)
    else:
        log("Skipping download and decompression")


    tf = tarfile.open(tar_name, 'r')
    log("Starting extraction from tar file " + tar_name)
    
    # Create the .update directory if necessary.
    if not os.path.exists(UPDATE_DIR):
        log("Creating {} directory".format(UPDATE_DIR))
        os.mkdir(UPDATE_DIR)
    
    # Extract the update files from the tar file to the .update directory.
    tar_members = (m for m in tf.getmembers() if os.path.basename(m.name) in UPDATE_FILES)
    for member in tar_members:
        ti = tf.extractfile(member)
        outfile = os.path.join(UPDATE_DIR, os.path.basename(member.name))
        try:
            with progress.FileProgress("Extracting", ti, outfile, ti.size) as extractor:
                extractor.start()
            log("Extracted " + outfile)
        except script_exceptions.Canceled:
            remove_update_files()
            sys.exit(0)
        except script_exceptions.WriteError as e:
            write_error(outfile, str(e))
            sys.exit(1)
        else:
            # Work around progress dialog bug (#13467) 
            del extractor

    tf.close()

    # Clean up the temporary files.
    try:
        if ext == '.bz2':
            log("Deleting {}".format(filename))
            os.remove(filename)

        if __addon__.getSetting('keep_tar') == "false":
            log("Deleting {}".format(tar_name))
            os.remove(tar_name)
    except OSError:
        pass
    

def verify(selected_build):
    # Verify the md5 sums.
    os.chdir(UPDATE_DIR)
    for f in UPDATE_IMAGES:
        md5sum = open(f + '.md5').read().split()[0]
        log("{}.md5 file = {}".format(f, md5sum))

        if not md5sum_verified(md5sum, f):
            log("{} md5 mismatch!".format(f))
            xbmcgui.Dialog().ok("{} md5 mismatch".format(f),
                                "The {} image from".format(f),
                                selected_build.filename,
                                "is corrupt. The update files will be removed.")
            remove_update_files()
            sys.exit(1)
        else:
            log("{} md5 is correct".format(f))
            

def notify(selected_build):
    log("Skipped reboot")
    xbmc.executebuiltin("Notification(OpenELEC Dev Update, Build {} will install "
                        "on the next reboot., 12000, {})".format(selected_build,
                                                                 __icon__))

def confirm(selected_build):
    from lib import constants
    
    with open(constants.NOTIFY_FILE, 'w') as f:
        f.write(str(selected_build))

    if __addon__.getSetting('confirm_reboot') == 'true':
        if xbmcgui.Dialog().yesno("Confirm reboot",
                                  " ",
                                  "Reboot now to install build {}?"
                                  .format(selected_build)):
            xbmc.restart() 
        else:
            notify(selected_build)
    else:
        TIMEOUT = 10
        progress = xbmcgui.DialogProgress()
        progress.create('Rebooting')
        
        restart = True
        seconds = TIMEOUT
        while seconds >= 0:
            progress.update(int((TIMEOUT - seconds) / TIMEOUT * 100),
                            "Build {} is ready to install.".format(selected_build),
                            "Rebooting{}{}...".format((seconds > 0) * " in {} second".format(seconds),
                                                      "s" * (seconds > 1)))
            xbmc.sleep(1000)
            if progress.iscanceled():
                restart = False
                break
            seconds -= 1
        progress.close()
        if restart:
            xbmc.restart()
        else:
            notify(selected_build)


UPDATE_DIR = '/storage/.update'
UPDATE_IMAGES = ('SYSTEM', 'KERNEL')

UPDATE_FILES = UPDATE_IMAGES + tuple(f + '.md5' for f in UPDATE_IMAGES)
UPDATE_PATHS = tuple(os.path.join(UPDATE_DIR, f) for f in UPDATE_FILES)

check_update_files()

with BuildList() as build_list:
    from lib.constants import __scriptid__
    
    __addon__ = xbmcaddon.Addon(__scriptid__)
    __icon__ = __addon__.getAddonInfo('icon')
    
    tmp_dir = __addon__.getSetting('tmp_dir')
    
    cd_tmp_dir()

    links = build_list.create()
    
selected_build = select_build(links)

download(selected_build)

verify(selected_build)

confirm(selected_build)
