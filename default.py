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
import urlparse
import hashlib
import tarfile
import glob

import xbmc, xbmcgui, xbmcaddon, xbmcvfs

from resources.lib import constants
from resources.lib import progress
from resources.lib import script_exceptions
from resources.lib import utils

__addon__ = xbmcaddon.Addon()
__icon__ = __addon__.getAddonInfo('icon')
__dir__ = xbmc.translatePath(__addon__.getAddonInfo('profile'))


def check_update_files():
    # Check if the update files are already in place.
    if (all(os.path.isfile(f) for f in constants.UPDATE_PATHS) or
        glob.glob(os.path.join(constants.UPDATE_DIR, '*tar'))):
        if xbmcgui.Dialog().yesno("Confirm reboot",
                                  "The update files are already in place.",
                                  "Reboot now to install the update",
                                  "or continue to select another build.",
                                  "Continue",
                                  "Reboot"):
            xbmc.restart()
        else:
            utils.remove_update_files()

def cd_tmp_dir():
    # Move to the download directory.
    try:
        os.makedirs(__dir__)
    except OSError:
        pass
    os.chdir(__dir__)
    utils.log("chdir to " + __dir__)

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


class BuildList():
    def __init__(self, arch, source):
        self._arch = arch
        self._source = source

    def create(self):
        import requests

        from resources.lib import builds

        try:
            self.installed_build = builds.get_installed_build()
        except requests.ConnectionError as e:
            utils.connection_error(str(e))
            sys.exit(1)
           
        subdir = __addon__.getSetting('subdir')
    
        # Get the url from the settings.
        utils.log("Source = " +  self._source)
        if self._source == "Other":
            # Custom URL
            url = __addon__.getSetting('custom_url')
            scheme, netloc = urlparse.urlparse(url)[:2]
            if not (scheme and netloc):
                utils.bad_url(url, "Invalid URL")
                sys.exit(1)
            
            build_url = builds.BuildsURL(url, subdir)
        else:
            # Defined URL
            try:
                build_url = builds.sources(self._arch)[self._source]
            except KeyError:
                utils.bad_source(self._source)
                sys.exit(1)
            else:
                if subdir:
                    utils.log("Using subdirectory = " + subdir)
                    build_url.add_subdir(subdir)
            url = build_url.url
        
        utils.log("Full URL = " + url)

        if __addon__.getSetting('set_timeout') == 'true':
            timeout = int(__addon__.getSetting('timeout'))
        else:
            timeout = None
    
        try:
            # Get the list of build links.
            with build_url.extractor() as extractor:
                links = sorted(set(extractor.get_links(self._arch, timeout)), reverse=True)
        except requests.ConnectionError as e:
            utils.connection_error(str(e))
            sys.exit(1)
        except builds.BuildURLError as e:
            utils.bad_url(url, str(e))
            sys.exit(1)
        except requests.RequestException as e:
            utils.url_error(url, str(e))
            sys.exit(1)

        if not links:
            utils.bad_url(url, "No builds were found for {}.".format(self._arch))
            sys.exit(1)
            
        return links
        
    def __enter__(self):
        xbmc.executebuiltin("ActivateWindow(busydialog)")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        xbmc.executebuiltin("Dialog.Close(busydialog)")


class Main(object):

    def __init__(self):
        utils.log("Starting")
        check_update_files()

        if __addon__.getSetting('set_arch') == 'true':
            self.arch = __addon__.getSetting('arch')
        else:
            self.arch = constants.ARCH
            
        self.source = __addon__.getSetting('source')

        with BuildList(self.arch, self.source) as build_list:
            self.background = __addon__.getSetting('background') == 'true'
            self.archive = __addon__.getSetting('archive') == 'true'
            self.archive_root = __addon__.getSetting('archive_root')
            self.verify_files = __addon__.getSetting('verify_files') == 'true'
            
            if self.archive:
                self.archive_tar_path = None
                self.archive_dir = os.path.join(self.archive_root, self.source)
                utils.log("Archive builds to " + self.archive_dir)
                if not xbmcvfs.exists(self.archive_root):
                    utils.log("Unable to access archive")
                    xbmcgui.Dialog().ok("Directory Error", "{} is not accessible.".format(self.archive_root),
                                        "Check the archive directory in the addon settings.")
                    __addon__.openSettings()
                    sys.exit(1)
                elif not xbmcvfs.mkdir(self.archive_dir):
                    utils.log("Unable to create directory in archive")
                    xbmcgui.Dialog().ok("Directory Error", "Unable to create {}.".format(self.archive_dir),
                                        "Check the archive directory permissions.")
                    sys.exit(1)

            cd_tmp_dir()
            
            self.links = build_list.create()            

            self.installed_build = build_list.installed_build
            
        self.select_build()

        self.maybe_download()
        
        self.maybe_copy_to_archive()

        self.maybe_extract()

        self.cleanup()

        self.maybe_verify()

        maybe_disable_overclock()

        maybe_schedule_extlinux_update()

        maybe_run_backup()

        self.confirm()

    def select_build(self):
        # TODO - what if INSTALLED_BUILD is a release with no date? 

        from resources.lib import gui

        build_select = gui.BuildSelect(self.arch)
        
        build_select.setSource(self.source)

        build_list = []
        for build in self.links:
            li = xbmcgui.ListItem(str(build))
            if build > self.installed_build:
                icon = 'upgrade'
            elif build < self.installed_build:
                icon = 'downgrade'
            else:
                icon = 'installed'
            li.setIconImage("{}.png".format(icon))
            build_list.append(li)
        build_select.setBuilds(build_list)

        build_select.doModal()

        if not build_select:
            sys.exit(0)

        selected_build = self.links[build_select.selected]
        utils.log("Selected build " + str(selected_build))
    
        # Confirm the update.
        msg = "{} -> {}?".format(self.installed_build, selected_build)
        if selected_build < self.installed_build:
            args = ("Confirm downgrade", "Downgrade", msg)
        elif selected_build > self.installed_build:
            args = ("Confirm upgrade", "Upgrade", msg)
        else:
            args = ("Confirm install",
                    "Build {} is already installed.".format(selected_build),
                    "Continue?")
        if not xbmcgui.Dialog().yesno(*args):
            sys.exit(0)
            
        self.selected_build = selected_build

    def maybe_download(self):
        import requests

        try:
            remote_file = self.selected_build.remote_file()
        except requests.RequestException as e:
            utils.url_error(self.selected_build.url, str(e))
            sys.exit(1)

        tar_name = self.selected_build.tar_name
        filename = self.selected_build.filename
        size = self.selected_build.size

        utils.log("Download URL = " + self.selected_build.url)
        utils.log("File name = " + filename)
        utils.log("File size = " + utils.size_fmt(size))
        
        if self.archive:
            self.archive_tar_path = os.path.join(self.archive_dir, self.selected_build.tar_name)
        
        if not self.copy_from_archive():
            try:
                if (os.path.isfile(filename) and
                    os.path.getsize(filename) == size):
                    # Skip the download if the file exists with the correct size.
                    utils.log("Skipping download")
                    pass
                else:
                    # Do the download
                    utils.log("Starting download of " + self.selected_build.url)
                    with progress.FileProgress("Downloading",
                                               remote_file, filename, size,
                                               self.background) as downloader:
                        downloader.start()
                    utils.log("Completed download of " + self.selected_build.url)  
            except script_exceptions.Canceled:
                sys.exit(0)
            except requests.RequestException as e:
                utils.url_error(self.selected_build.url, str(e))
                sys.exit(1)
            except script_exceptions.WriteError as e:
                utils.write_error(os.path.join(__dir__, filename), str(e))
                sys.exit(1)

        # Do the decompression if necessary.
        if self.selected_build.compressed and not os.path.isfile(tar_name):
            try:
                bf = open(filename, 'rb')
                utils.log("Starting decompression of " + filename)
                with progress.DecompressProgress("Decompressing",
                                                 bf, tar_name, size,
                                                 self.background) as decompressor:
                    decompressor.start()
                utils.log("Completed decompression of " + filename)
            except script_exceptions.Canceled:
                sys.exit(0)
            except script_exceptions.WriteError as e:
                utils.write_error(os.path.join(__dir__, tar_name), str(e))
                sys.exit(1)
            except script_exceptions.DecompressError as e:
                utils.decompress_error(os.path.join(__dir__, filename), str(e))
                sys.exit(1)

        __addon__.setSetting('update_pending', 'true')

    def maybe_extract(self):
        # Create the .update directory if necessary.
        if not os.path.exists(constants.UPDATE_DIR):
            utils.log("Creating {} directory".format(constants.UPDATE_DIR))
            os.mkdir(constants.UPDATE_DIR)

        if self.verify_files:
            tf = tarfile.open(self.selected_build.tar_name, 'r')
            utils.log("Starting extraction from tar file " + self.selected_build.tar_name)
            
            # Extract the update files from the tar file to the .update directory.
            tar_members = (m for m in tf.getmembers()
                           if os.path.basename(m.name) in constants.UPDATE_FILES)
            for member in tar_members:
                ti = tf.extractfile(member)
                outfile = os.path.join(constants.UPDATE_DIR, os.path.basename(member.name))
                try:
                    with progress.FileProgress("Extracting", ti, outfile, ti.size,
                                               self.background) as extractor:
                        extractor.start()
                    utils.log("Extracted " + outfile)
                except script_exceptions.Canceled:
                    utils.remove_update_files()
                    sys.exit(0)
                except script_exceptions.WriteError as e:
                    utils.write_error(outfile, str(e))
                    sys.exit(1)
    
            tf.close()
        else:
            # Just move the tar file to the update directory.
            os.rename(self.selected_build.tar_name,
                      os.path.join(constants.UPDATE_DIR, self.selected_build.tar_name))

    def copy_from_archive(self):
        if self.archive:
            if xbmcvfs.exists(self.archive_tar_path):
                utils.log("Skipping download and decompression")
        
                archive = xbmcvfs.File(self.archive_tar_path)
                tarfile = os.path.join(__dir__, self.selected_build.tar_name)
        
                try:
                    with progress.FileProgress("Retrieving tar file from archive",
                                               archive, tarfile, archive.size(),
                                               self.background) as extractor:
                        extractor.start()
                except script_exceptions.Canceled:
                    self.cleanup()
                    sys.exit(0)
                except script_exceptions.WriteError:
                    sys.exit(1)
                
                return True
        
        return False

    def maybe_copy_to_archive(self):
        if self.archive and not xbmcvfs.exists(self.archive_tar_path):
            utils.log("Archiving tar file to {}".format(self.archive_tar_path))

            tarpath = os.path.join(__dir__, self.selected_build.tar_name)
            tar = open(tarpath)
            size = os.path.getsize(tarpath)

            try:
                with progress.FileProgress("Copying to archive",
                                           tar, self.archive_tar_path, size,
                                           self.background) as extractor:
                    extractor.start()
            except script_exceptions.Canceled:
                utils.log("Archive copy canceled")
                xbmcvfs.delete(self.archive_tar_path)
            except script_exceptions.WriteError as e:
                utils.write_error(self.archive_tar_path, str(e))
                xbmcvfs.delete(self.archive_tar_path)

    def cleanup(self):
        # Clean up the temporary files.
        try:
            if self.selected_build.compressed:
                utils.log("Deleting temporary {}".format(self.selected_build.filename))
                os.remove(self.selected_build.filename)

            utils.log("Deleting temporary {}".format(self.selected_build.tar_name))
            os.remove(self.selected_build.tar_name)
        except OSError:
            pass

    def md5sum_verified(self, md5sum_compare, path):
        if self.background:
            verify_progress = progress.ProgressBG()
        else:
            verify_progress = progress.Progress()
            
        verify_progress.create("Verifying", line2=path)
    
        BLOCK_SIZE = 8192
        
        hasher = hashlib.md5()
        f = open(path)
        
        done = 0
        size = os.path.getsize(path)
        while done < size:
            if verify_progress.iscanceled():
                verify_progress.close()
                return True
            data = f.read(BLOCK_SIZE)
            done += len(data)
            hasher.update(data)
            percent = int(done * 100 / size)
            verify_progress.update(percent)
        verify_progress.close()
            
        md5sum = hasher.hexdigest()
        utils.log("{} md5 hash = {}".format(path, md5sum))
        return md5sum == md5sum_compare

    def maybe_verify(self):
        if self.verify_files:
            # Verify the md5 sums.
            os.chdir(constants.UPDATE_DIR)
            for f in constants.UPDATE_IMAGES:
                md5sum = open(f + '.md5').read().split()[0]
                utils.log("{}.md5 file = {}".format(f, md5sum))
        
                if not self.md5sum_verified(md5sum, f):
                    utils.log("{} md5 mismatch!".format(f))
                    xbmcgui.Dialog().ok("{} md5 mismatch".format(f),
                                        "The {} image from".format(f),
                                        self.selected_build.filename,
                                        "is corrupt. The update files will be removed.")
                    utils.remove_update_files()
                    sys.exit(1)
                else:
                    utils.log("{} md5 is correct".format(f))

    def confirm(self):
        with open(os.path.join(__dir__, constants.NOTIFY_FILE), 'w') as f:
            f.write(str(self.selected_build))

        if __addon__.getSetting('confirm_reboot') == 'true':
            if xbmcgui.Dialog().yesno("Confirm reboot",
                                      " ",
                                      "Reboot now to install build {}?"
                                      .format(self.selected_build)):
                xbmc.restart() 
            else:
                utils.notify("Build {} will install on the next reboot".format(self.selected_build))
        else:
            if progress.restart_countdown("Build {} is ready to install.".format(self.selected_build)):
                xbmc.restart()
            else:
                utils.notify("Build {} will install on the next reboot".format(self.selected_build))


Main()




