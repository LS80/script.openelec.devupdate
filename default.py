############################################################################
#
#  Copyright 2012 Lee Smith
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
# 
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
# 
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#################################################imp###########################

from __future__ import division

import os
import sys

import xbmc, xbmcgui, xbmcaddon
import requests2 as requests

from lib import constants

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
    utils.log("{} md5 hash = {}".format(path, md5sum))
    return md5sum == md5sum_compare


def check_update_files():
    # Check if the update files are already in place.
    if all(os.path.isfile(f) for f in constants.UPDATE_PATHS):
        if xbmcgui.Dialog().yesno("Confirm reboot",
                                  "The update files are already in place.",
                                  "Reboot now to install the update",
                                  "or continue to select another build.",
                                  "Continue",
                                  "Reboot"):
            xbmc.restart()


def cd_tmp_dir():
    # Move to the download directory.
    try:
        os.makedirs(tmp_dir)
    except OSError:
        pass
    os.chdir(tmp_dir)
    utils.log("chdir to " + tmp_dir)
    
    
class BuildList():

    def create(self):
        import urllib2
        import urlparse
        import socket

        import xbmcvfs

        from lib import builds
        
        subdir = __addon__.getSetting('subdir')
    
        # Get the url from the settings.
        source = __addon__.getSetting('source')
        utils.log("Source = " +  source)
        if source == "Other":
            # Custom URL
            url = __addon__.getSetting('custom_url')
            scheme, netloc = urlparse.urlparse(url)[:2]
            if not (scheme and netloc):
                utils.bad_url(url, "Invalid URL")
                sys.exit(1)
            
            build_url = builds.BuildsURL(url, subdir)
        else:
            # Defined URL
            build_url = builds.URLS[source]
            url = build_url.url
        
        utils.log("Full URL = " + url)
    
        try:
            # Get the list of build links.
            with build_url.extractor() as extractor:
                links = sorted(set(extractor.get_links()), reverse=True)
        except builds.BuildURLError as e:
            utils.bad_url(url, str(e))
            sys.exit(1)
        except (requests.RequestException, socket.error) as e:
            utils.url_error(url, str(e))
            sys.exit(1)
        
        if __addon__.getSetting('archive') == "true":
            # Look in archive area for local build files.
            archive_dir = os.path.join(archive_root, source)
            files = xbmcvfs.listdir(archive_dir)[1]
            for link in links:
                if link.tar_name in files:
                    link.set_archive(archive_dir)

        if not links:
            utils.bad_url(url, "No builds were found for {}.".format(constants.ARCH))
            sys.exit(1)
            
        return source, links
        
    def __enter__(self):
        xbmc.executebuiltin("ActivateWindow(busydialog)")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        xbmc.executebuiltin("Dialog.Close(busydialog)")


def select_build(source, links):
    from lib.builds import INSTALLED_BUILD, ARCH
    
    # TODO - what if INSTALLED_BUILD is a release with no date? 

    # Ask which build to install.
    i = xbmcgui.Dialog().select("{} {} (* = installed)".format(ARCH, source),
                                [str(r) + ' *'*(r == INSTALLED_BUILD) for r in links])
    if i == -1:
        sys.exit(0)
    selected_build = links[i]
    utils.log("Selected build " + str(selected_build))

    # Confirm the update.
    msg = "{} -> {}?".format(INSTALLED_BUILD, selected_build)
    if selected_build < INSTALLED_BUILD:
        args = ("Confirm downgrade", "Downgrade", msg)
    elif selected_build > INSTALLED_BUILD:
        args = ("Confirm upgrade", "Upgrade", msg)
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

    from lib import progress
    from lib import script_exceptions

    tar_name = selected_build.tar_name
    filename = selected_build.filename

    utils.log("Download URL = " + selected_build.url)
    req = urllib2.Request(selected_build.url, None)

    try:
        rf = urllib2.urlopen(req)
        utils.log("Opened URL " + selected_build.url)
        bz2_size = int(rf.headers.getheader('Content-Length'))
        utils.log("Size of file = " + utils.size_fmt(bz2_size))

        if (os.path.isfile(filename) and
            os.path.getsize(filename) == bz2_size):
            # Skip the download if the file exists with the correct size.
            utils.log("Skipping download")
            pass
        else:
            # Do the download
            utils.log("Starting download of " + selected_build.url)
            with progress.FileProgress("Downloading", rf, filename, bz2_size) as downloader:
                downloader.start()
            utils.log("Completed download of " + selected_build.url)  
    except script_exceptions.Canceled:
        sys.exit(0)
    except (urllib2.HTTPError, socket.error) as e:
        utils.url_error(selected_build.url, str(e))
        sys.exit(1)
    except script_exceptions.WriteError as e:
        utils.write_error(os.path.join(tmp_dir, filename), str(e))
        sys.exit(1)


    # Do the decompression if necessary.
    if selected_build.compressed and not os.path.isfile(tar_name):
        try:
            bf = open(filename, 'rb')
            utils.log("Starting decompression of " + filename)
            with progress.DecompressProgress("Decompressing", bf, tar_name, bz2_size) as decompressor:
                decompressor.start()
            utils.log("Completed decompression of " + filename)
        except script_exceptions.Canceled:
            sys.exit(0)
        except script_exceptions.WriteError as e:
            utils.write_error(os.path.join(tmp_dir, tar_name), str(e))
            sys.exit(1)
        except script_exceptions.DecompressError as e:
            utils.decompress_error(os.path.join(tmp_dir, filename), str(e))
            sys.exit(1)            


def extract(selected_build):
    import tarfile
    
    from lib import progress
    from lib import script_exceptions

    tf = tarfile.open(selected_build.tar_name, 'r')
    utils.log("Starting extraction from tar file " + selected_build.tar_name)
    
    # Create the .update directory if necessary.
    if not os.path.exists(constants.UPDATE_DIR):
        utils.log("Creating {} directory".format(constants.UPDATE_DIR))
        os.mkdir(constants.UPDATE_DIR)
    
    # Extract the update files from the tar file to the .update directory.
    tar_members = (m for m in tf.getmembers() if os.path.basename(m.name) in constants.UPDATE_FILES)
    for member in tar_members:
        ti = tf.extractfile(member)
        outfile = os.path.join(constants.UPDATE_DIR, os.path.basename(member.name))
        try:
            with progress.FileProgress("Extracting", ti, outfile, ti.size) as extractor:
                extractor.start()
            utils.log("Extracted " + outfile)
        except script_exceptions.Canceled:
            utils.remove_update_files()
            sys.exit(0)
        except script_exceptions.WriteError as e:
            utils.write_error(outfile, str(e))
            sys.exit(1)
        else:
            # Work around progress dialog bug (#13467) 
            del extractor

    tf.close()


def maybe_copy_to_archive(source, selected_build):
    if __addon__.getSetting('archive') == "true" and selected_build.archive is None:
        archive_dir = os.path.join(archive_root, source)
        archive_file = os.path.join(archive_dir, selected_build.tar_name)
        progress = xbmcgui.DialogProgress()
        msg = 'Copying tar file to archive'
        progress.create('Archiving build', ' ', msg, ' ')
        progress.update(0, ' ', msg, ' ')
        xbmcvfs.mkdir(archive_dir)
        success = xbmcvfs.copy(os.path.join(__dir__, selected_build.tar_name), archive_file)
        if progress.iscanceled():
            xbmcvfs.delete(archive_file)
        progress.close()


def cleanup(selected_build):

    # Clean up the temporary files.
    try:
        if selected_build.compressed:
            utils.log("Deleting {}".format(selected_build.filename))
            os.remove(selected_build.filename)

        utils.log("Deleting {}".format(selected_build.tar_name))
        os.remove(selected_build.tar_name)
    except OSError:
        pass


def copy_from_archive(selected_build):
    utils.log("Skipping download and decompression")
    progress = xbmcgui.DialogProgress()
    msg = 'Retrieving tar file from archive'
    progress.create('Retrieving build', ' ', msg, ' ')
    progress.update(0, ' ', msg, ' ')
    success = xbmcvfs.copy(selected_build.archive, os.path.join(__dir__, selected_build.tar_name))
    if progress.iscanceled():
        cleanup(selected_build)
        sys.exit(0)
    progress.close()    
    

def verify(selected_build):
    # Verify the md5 sums.
    os.chdir(constants.UPDATE_DIR)
    for f in constants.UPDATE_IMAGES:
        md5sum = open(f + '.md5').read().split()[0]
        utils.log("{}.md5 file = {}".format(f, md5sum))

        if not md5sum_verified(md5sum, f):
            utils.log("{} md5 mismatch!".format(f))
            xbmcgui.Dialog().ok("{} md5 mismatch".format(f),
                                "The {} image from".format(f),
                                selected_build.filename,
                                "is corrupt. The update files will be removed.")
            utils.remove_update_files()
            sys.exit(1)
        else:
            utils.log("{} md5 is correct".format(f))

            
def maybe_disable_overclock():
    import re
    
    if (constants.ARCH == 'RPi.arm' and
        os.path.isfile(constants.RPI_CONFIG_PATH) and
        __addon__.getSetting('disable_overclock') == 'true'):
        
        with open(constants.RPI_CONFIG_PATH, 'r') as a:
            config = a.read()
        
        if constants.RPI_OVERCLOCK_RE.search(config):

            xbmcvfs.copy(constants.RPI_CONFIG_PATH,
                         os.path.join(__dir__, constants.RPI_CONFIG_FILE))

            def repl(m):
                return '#' + m.group(1)
            
            utils.mount_readwrite()

            with open(constants.RPI_CONFIG_PATH, 'w') as b:
                b.write(re.sub(constants.RPI_OVERCLOCK_RE, repl, config))

            utils.mount_readonly()


def maybe_schedule_extlinux_update():
    if (constants.ARCH != 'RPi.arm' and
        __addon__.getSetting('update_extlinux') == 'true'):
        open(os.path.join(__dir__, constants.UPDATE_EXTLINUX), 'w').close()


def maybe_run_backup():
    backup = int(__addon__.getSetting('backup'))
    if backup == 0:
        do_backup = False
    elif backup == 1:
        do_backup = xbmcgui.Dialog().yesno("Backup",
                                           "Run XBMC Backup now?",
                                           "This is recommended")
        utils.log("Backup requested")
    elif backup == 2:
        do_backup = True
        utils.log("Backup always")

    if do_backup:
        xbmc.executebuiltin('RunScript(script.xbmcbackup, mode=backup)')


def notify(selected_build):
    utils.log("Skipped reboot")
    xbmc.executebuiltin("Notification(OpenELEC Dev Update, Build {} will install "
                        "on the next reboot., 12000, {})".format(selected_build,
                                                                 __icon__))

def confirm(selected_build):
    from lib import progress

    with open(os.path.join(__dir__, constants.NOTIFY_FILE), 'w') as f:
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
        if progress.restart_countdown("Build {} is ready to install.".format(selected_build)):
            xbmc.restart()
        else:
            notify(selected_build)



check_update_files()

with BuildList() as build_list:
    import urllib2
    import socket
    
    import xbmcvfs

    from lib import utils
    
    __addon__ = xbmcaddon.Addon()
    __icon__ = __addon__.getAddonInfo('icon')
    __dir__ = xbmc.translatePath(__addon__.getAddonInfo('profile'))

    if __addon__.getSetting('archive') == "true":
        archive_root = __addon__.getSetting('archive_root')
        if not xbmcvfs.exists(archive_root):
            xbmcgui.Dialog().ok("Directory Error", "{} is not accessible.".format(archive_root),
                                "Check the archive directory in the addon settings.")
            __addon__.openSettings()
            sys.exit(1)
    
    tmp_dir = __dir__
    
    cd_tmp_dir()
    
    if __addon__.getSetting('set_timeout') == 'true':
        timeout = int(__addon__.getSetting('timeout'))
        socket.setdefaulttimeout(timeout)
    else:
        socket.setdefaulttimeout(None)

    try:
        source, links = build_list.create()
    except urllib2.URLError:
        xbmcgui.Dialog().ok("Connection Error",
                            "Check that you are connected to the internet.", " ")
        __addon__.openSettings()
        sys.exit(1)
    
selected_build = select_build(source, links)

if selected_build.archive is not None:
    copy_from_archive(selected_build)
else:
    download(selected_build)

extract(selected_build)

maybe_copy_to_archive(source, selected_build)

cleanup(selected_build)

verify(selected_build)

maybe_disable_overclock()

maybe_schedule_extlinux_update()

maybe_run_backup()

confirm(selected_build)
