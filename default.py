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
import hashlib
import tarfile
import glob
from urlparse import urlparse
import threading

import xbmc, xbmcgui, xbmcaddon, xbmcvfs
import requests

from resources.lib import constants
from resources.lib import progress
from resources.lib import script_exceptions
from resources.lib import utils
from resources.lib.funcs import size_fmt
from resources.lib import builds
from resources.lib import openelec

addon = xbmcaddon.Addon(constants.ADDON_ID)

ADDON_DATA = xbmc.translatePath(addon.getAddonInfo('profile'))
ADDON_PATH = xbmc.translatePath(addon.getAddonInfo('path'))
ADDON_NAME = addon.getAddonInfo('name')


def check_update_files():
    # Check if the update files are already in place.
    if (all(os.path.isfile(f) for f in constants.UPDATE_PATHS) or
        glob.glob(os.path.join(constants.UPDATE_DIR, '*tar'))):
        notify_file = os.path.join(ADDON_DATA, constants.NOTIFY_FILE)
        try:
            with open(notify_file) as f:
                selected = f.read()
            s = " for "
        except IOError:
            s = selected = ""
        msg = ("An installation is pending{}"
               "[COLOR=lightskyblue][B]{}[/B][/COLOR].").format(s, selected)
        if xbmcgui.Dialog().yesno("Confirm reboot",
                                  msg,
                                  "Reboot now to install the update",
                                  "or continue to select another build.",
                                  "Continue",
                                  "Reboot"):
            xbmc.restart()
            sys.exit(0)
        else:
            utils.remove_update_files()

def cd_tmp_dir():
    # Move to the download directory.
    try:
        os.makedirs(ADDON_DATA)
    except OSError:
        pass
    os.chdir(ADDON_DATA)
    utils.log("chdir to " + ADDON_DATA)

def maybe_disable_overclock():
    import re
    
    if (constants.ARCH.startswith('RPi') and
        os.path.isfile(constants.RPI_CONFIG_PATH) and
        addon.getSetting('disable_overclock') == 'true'):
        
        with open(constants.RPI_CONFIG_PATH, 'r') as a:
            config = a.read()
        
        if constants.RPI_OVERCLOCK_RE.search(config):

            xbmcvfs.copy(constants.RPI_CONFIG_PATH,
                         os.path.join(ADDON_DATA, constants.RPI_CONFIG_FILE))

            def repl(m):
                return '#' + m.group(1)
            
            openelec.mount_readwrite()

            with open(constants.RPI_CONFIG_PATH, 'w') as b:
                b.write(re.sub(constants.RPI_OVERCLOCK_RE, repl, config))

            openelec.mount_readonly()

def maybe_schedule_extlinux_update():
    if (constants.ARCH != 'RPi.arm' and
        addon.getSetting('update_extlinux') == 'true'):
        open(os.path.join(ADDON_DATA, constants.UPDATE_EXTLINUX), 'w').close()

def maybe_run_backup():
    backup = int(addon.getSetting('backup'))
    if backup == 0:
        do_backup = False
    elif backup == 1:
        do_backup = xbmcgui.Dialog().yesno("Backup",
                                           "Run Backup now?",
                                           "This is recommended")
        utils.log("Backup requested")
    elif backup == 2:
        do_backup = True
        utils.log("Backup always")

    if do_backup:
        xbmc.executebuiltin('RunScript(script.xbmcbackup, mode=backup)', True)
        xbmc.sleep(10000)
        window = xbmcgui.Window(10000)
        while (window.getProperty('script.xbmcbackup.running') == 'true'):
            xbmc.sleep(5000)


class BuildDetailsDialog(xbmcgui.WindowXMLDialog):
    def __new__(cls, _1, _2):
        return super(BuildDetailsDialog, cls).__new__(cls, "Details.xml", ADDON_PATH)

    def __init__(self, build, text):
        self._build = build
        self._text = text

    def onInit(self):
        self.getControl(1).setText(self._build)
        self.getControl(2).setText(self._text)

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_SHOW_INFO,
                         xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()


class BuildSelectDialog(xbmcgui.WindowXMLDialog):
    LABEL_ID = 100
    BUILD_LIST_ID = 20
    SOURCE_LIST_ID = 10
    BUILD_INFO_ID = 200
    SETTINGS_BUTTON_ID = 30
    
    def __new__(cls, _):
        return super(BuildSelectDialog, cls).__new__(cls, "Dialog.xml", ADDON_PATH)
    
    def __init__(self, installed_build):
        self._installed_build = installed_build

        if addon.getSetting('set_arch') == 'true':
            self._arch = addon.getSetting('arch')
        else:
            self._arch = constants.ARCH
            
        if addon.getSetting('set_timeout') == 'true':
            self._timeout = int(addon.getSetting('timeout'))
        else:
            self._timeout = None
        
        self._sources = builds.sources(self._arch)

        if addon.getSetting('custom_source_enable') == 'true':
            custom_name = addon.getSetting('custom_source')
            custom_url = addon.getSetting('custom_url')
            scheme, netloc = urlparse(custom_url)[:2]
            if not scheme in ('http', 'https') or not netloc:
                utils.bad_url(custom_url, "Invalid custom source URL")
            else:
                custom_extractors = (builds.BuildLinkExtractor,
                                     builds.ReleaseLinkExtractor,
                                     builds.MilhouseBuildLinkExtractor)

                build_type = addon.getSetting('build_type')
                try:
                    build_type_index = int(build_type)
                except ValueError:
                    utils.log("Invalid build type index '{}'".format(build_type),
                              xbmc.LOGERROR)
                    build_type_index = 0
                extractor = custom_extractors[build_type_index]

                self._sources[custom_name] = builds.BuildsURL(custom_url,
                                                              extractor=extractor)

        self._initial_source = addon.getSetting('source_name')
        try:
            self._build_url = self._sources[self._initial_source]
        except KeyError:
            self._build_url = self._sources.itervalues().next()
            self._initial_source = self._sources.iterkeys().next()
        self._builds = self._get_build_links(self._build_url)

        self._build_infos = {}

    def __nonzero__(self):
        return self._selected_build is not None

    def onInit(self):
        self._selected_build = None

        self._sources_list = self.getControl(self.SOURCE_LIST_ID)
        self._sources_list.addItems(self._sources.keys())
        
        self._build_list = self.getControl(self.BUILD_LIST_ID)
        
        label = "Arch: {0}".format(self._arch)
        self.getControl(self.LABEL_ID).setLabel(label)

        self._info_textbox = self.getControl(self.BUILD_INFO_ID)

        if self._builds:
            self._selected_source_position = self._sources.keys().index(self._initial_source)

            self._set_builds(self._builds)
        else:
            self._selected_source_position = 0
            self._initial_source = self._sources.iterkeys().next()
            self.setFocusId(self.SOURCE_LIST_ID)

        self._selected_source = self._initial_source

        self._sources_list.selectItem(self._selected_source_position)

        item = self._sources_list.getListItem(self._selected_source_position)
        self._selected_source_item = item
        self._selected_source_item.setLabel2('selected')

        threading.Thread(target=self._get_and_set_build_info,
                         args=(self._build_url,)).start()

    @property
    def selected_build(self):
        return self._selected_build

    @property
    def selected_source(self):
        return self._selected_source

    def onClick(self, controlID):
        if controlID == self.BUILD_LIST_ID:
            self._selected_build = self._builds[self._build_list.getSelectedPosition()]
            self.close()
        elif controlID == self.SOURCE_LIST_ID:
            self._build_url = self._get_build_url()
            build_links = self._get_build_links(self._build_url)

            if build_links:
                self._selected_source_item.setLabel2('')
                self._selected_source_item = self._sources_list.getSelectedItem()
                self._selected_source_position = self._sources_list.getSelectedPosition()
                self._selected_source_item.setLabel2('selected')
                self._selected_source = self._selected_source_item.getLabel()

                self._set_builds(build_links)

                threading.Thread(target=self._get_and_set_build_info,
                                 args=(self._build_url,)).start()
            else:
                self._sources_list.selectItem(self._selected_source_position)
        elif controlID == self.SETTINGS_BUTTON_ID:
            self.close()
            addon.openSettings()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_MOVE_DOWN, xbmcgui.ACTION_MOVE_UP,
                         xbmcgui.ACTION_PAGE_DOWN, xbmcgui.ACTION_PAGE_UP,
                         xbmcgui.ACTION_MOUSE_MOVE):
            self._set_build_info()

        elif action_id == xbmcgui.ACTION_SHOW_INFO:
            build_version = self._build_list.getSelectedItem().getLabel()
            try:
                info = self._build_infos[build_version]
            except KeyError:
                utils.log("Build details for build {} not found".format(build_version))
            else:
                build = "[B]Build #{}[/B]\n\n".format(build_version)
                if info.details is not None:
                    try:
                        details = info.details.get_text()
                    except Exception as e:
                        utils.log("Unable to retrieve build details: {}".format(e))
                    else:
                        if details:
                            dialog = BuildDetailsDialog(build, details)
                            dialog.doModal()

        elif action_id in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()

    def onFocus(self, controlID):
        if controlID == self.BUILD_LIST_ID:
            self._builds_focused = True
        else:
            self._builds_focused = False

    @utils.showbusy
    def _get_build_links(self, build_url):
        links = []
        try:
            # Get the list of build links.
            with build_url.extractor() as extractor:
                links = sorted(set(extractor.get_links(self._arch, self._timeout)),
                               reverse=True)
        except requests.ConnectionError as e:
            utils.connection_error(str(e))
        except builds.BuildURLError as e:
            utils.bad_url(build_url.url, str(e))
        except requests.RequestException as e:
            utils.url_error(build_url.url, str(e))
        else:
            if not links:
                utils.bad_url(build_url.url,
                              "No builds were found for {}.".format(self._arch))
        return links

    def _get_build_infos(self, build_url):
        utils.log("Retrieving build information")
        info = {}
        for info_extractor in build_url.info_extractors:
            try:
                with info_extractor:
                    info.update(info_extractor.get_info(self._timeout))
            except Exception as e:
                utils.log("Unable to retrieve build info: {}".format(str(e)))
        return info
                
    def _set_build_info(self):
        info = ""
        if self._builds_focused:
            selected_item = self._build_list.getSelectedItem()
            try:
                build_version = selected_item.getLabel()
            except AttributeError:
                utils.log("Unable to get selected build name")
            else:
                try:
                    info = self._build_infos[build_version].summary
                except KeyError:
                    utils.log("Build info for build {} not found".format(build_version))
                else:
                    utils.log("Info for build {}:\n\t{}".format(build_version, info))
        self._info_textbox.setText(info)

    def _get_and_set_build_info(self, build_url):
        self._build_infos = self._get_build_infos(build_url)
        self._set_build_info()

    def _get_build_url(self):
        source = self._sources_list.getSelectedItem().getLabel()     
        build_url = self._sources[source]

        #subdir = addon.getSetting('subdir')
        #if subdir:
        #    utils.log("Using subdirectory = " + subdir)
        #    build_url.add_subdir(subdir)

        utils.log("Full URL = " + build_url.url)
        return build_url

    def _set_builds(self, builds):
        self._builds = builds
        self._build_list.reset()
        for build in builds:
            li = xbmcgui.ListItem()
            li.setLabel(build.version)
            li.setLabel2(build.date)
            if build > self._installed_build:
                icon = 'upgrade'
            elif build < self._installed_build:
                icon = 'downgrade'
            else:
                icon = 'installed'
            li.setIconImage("{}.png".format(icon))
            self._build_list.addItem(li)
        self.setFocusId(self.BUILD_LIST_ID)
        self._builds_focused = True


class Main(object):
    def __init__(self):
        utils.log("Starting")
        check_update_files()

        self.background = addon.getSetting('background') == 'true'
        self.verify_files = addon.getSetting('verify_files') == 'true'
        
        self.installed_build = self.get_installed_build()

        cd_tmp_dir()
            
        self.select_build()

        self.check_archive()

        self.maybe_download()
        
        self.maybe_copy_to_archive()

        self.maybe_extract()

        self.cleanup()

        self.maybe_verify()

        maybe_disable_overclock()

        maybe_schedule_extlinux_update()

        maybe_run_backup()

        self.confirm()

    def get_installed_build(self):        
        try:
            return builds.get_installed_build()
        except requests.ConnectionError as e:
            utils.connection_error(str(e))
            sys.exit(1)

    def check_archive(self):
        self.archive = addon.getSetting('archive') == 'true'
        if self.archive:
            archive_root = addon.getSetting('archive_root')
            self.archive_root = utils.ensure_trailing_slash(archive_root)
            self.archive_tar_path = None
            self.archive_dir = os.path.join(self.archive_root, str(self.selected_source))
            utils.log("Archive builds to " + self.archive_dir)
            if not xbmcvfs.exists(self.archive_root):
                utils.log("Unable to access archive")
                xbmcgui.Dialog().ok("Directory Error",
                                    "{} is not accessible.".format(self.archive_root),
                                    "Check the archive directory in the addon settings.")
                addon.openSettings()
                sys.exit(1)
            elif not xbmcvfs.mkdir(self.archive_dir):
                utils.log("Unable to create directory in archive")
                xbmcgui.Dialog().ok("Directory Error",
                                    "Unable to create {}.".format(self.archive_dir),
                                    "Check the archive directory permissions.")
                sys.exit(1)

    def select_build(self):
        build_select = BuildSelectDialog(self.installed_build)
        build_select.doModal()
        
        self.selected_source = build_select.selected_source
        addon.setSetting('source_name', self.selected_source)
        utils.log("Selected source: " + str(self.selected_source))
        
        if not build_select:
            utils.log("No build selected")
            sys.exit(0)

        selected_build = build_select.selected_build
        utils.log("Selected build: " + str(selected_build))
    
        # Confirm the update.
        msg = ("[COLOR=lightskyblue][B]{}[/B][/COLOR]"
               "  to  [COLOR=lightskyblue][B]{}[/B][/COLOR] ?").format(self.installed_build,
                                                                       selected_build)
        if selected_build < self.installed_build:
            args = ("Confirm downgrade", "Downgrade", msg)
        elif selected_build > self.installed_build:
            args = ("Confirm upgrade", "Upgrade", msg)
        else:
            msg = ("Build  [COLOR=lightskyblue][B]{}[/B][/COLOR]"
                   "  is already installed.").format(selected_build)
            args = ("Confirm install", msg, "Continue?")
        if not xbmcgui.Dialog().yesno(*args):
            sys.exit(0)
            
        self.selected_build = selected_build

    def maybe_download(self):
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
        utils.log("File size = " + size_fmt(size))
        
        if self.archive:
            self.archive_tar_path = os.path.join(self.archive_dir,
                                                 self.selected_build.tar_name)
        
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
                utils.write_error(os.path.join(ADDON_DATA, filename), str(e))
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
                utils.write_error(os.path.join(ADDON_DATA, tar_name), str(e))
                sys.exit(1)
            except script_exceptions.DecompressError as e:
                utils.decompress_error(os.path.join(ADDON_DATA, filename), str(e))
                sys.exit(1)

        addon.setSetting('update_pending', 'true')

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
            # Just move the tar file to the .update directory.
            dest = os.path.join(constants.UPDATE_DIR, self.selected_build.tar_name)
            utils.log("Moving to " + dest)
            os.rename(self.selected_build.tar_name, dest)

    def copy_from_archive(self):
        if self.archive:
            if xbmcvfs.exists(self.archive_tar_path):
                utils.log("Skipping download and decompression")
        
                archive = xbmcvfs.File(self.archive_tar_path)
                tarfile = os.path.join(ADDON_DATA, self.selected_build.tar_name)
        
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

            tarpath = os.path.join(ADDON_DATA, self.selected_build.tar_name)
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
        with open(os.path.join(ADDON_DATA, constants.NOTIFY_FILE), 'w') as f:
            f.write(str(self.selected_build))

        if addon.getSetting('confirm_reboot') == 'true':
            if xbmcgui.Dialog().yesno(
                    "Confirm reboot",
                    " ",
                    "Reboot now to install build  [COLOR=lightskyblue][B]{}[/COLOR][/B] ?"
                    .format(self.selected_build)):
                xbmc.restart() 
            else:
                utils.notify("Build {} will install on the next reboot"
                             .format(self.selected_build))
        else:
            if progress.restart_countdown("Build  [COLOR=lightskyblue][B]{}[/COLOR][/B]"
                                          "  is ready to install."
                                          .format(self.selected_build)):
                xbmc.restart()
            else:
                utils.notify("Build {} will install on the next reboot"
                             .format(self.selected_build))


def check_for_new_build():
    utils.log("Checking for a new build")
    
    check_official = addon.getSetting('check_official') == 'true'
    check_interval = int(addon.getSetting('check_interval'))

    autoclose_ms = check_interval * 3540000 # check interval in ms - 1 min
    
    try:
        installed_build = builds.get_installed_build()
    except:
        utils.log("Unable to get installed build so exiting")
        sys.exit(1)

    source = addon.getSetting('source_name')
    if (isinstance(installed_build, builds.Release) and source == "Official Releases"
        and not check_official):
        # Don't do the job of the official auto-update system.
        utils.log("Skipping build check - official release")
    else:
        if addon.getSetting('set_arch') == 'true':
            arch = addon.getSetting('arch')
        else:
            arch = constants.ARCH

        build_sources = builds.sources(arch)
        try:
            build_url = build_sources[source]
        except KeyError:
            utils.log("{} is not a valid source".format(source))
            return

        utils.log("Checking {}".format(build_url.url))

        if addon.getSetting('set_timeout') == 'true':
            timeout = int(addon.getSetting('timeout'))
        else:
            timeout = None

        latest = builds.latest_build(arch, source, timeout)
        if latest and latest > installed_build:
            if utils.build_check_prompt():
                utils.log("New build {} is available, "
                          "prompting to show build list".format(latest))

                if xbmcgui.Dialog().yesno(
                        ADDON_NAME,
                        line1="A more recent build is available:"
                        "   [COLOR lightskyblue][B]{}[/B][/COLOR]".format(latest),
                        line2="Current build:"
                        "   [COLOR lightskyblue][B]{}[/B][/COLOR]".format(installed_build),
                        line3="Show builds available to install?",
                        autoclose=autoclose_ms):
                    Main()
            else:
                utils.log("Notifying that new build {} is available".format(latest))
                utils.notify("Build {} is available".format(latest), 7500)


def notify_installation():
    notify_file = os.path.join(ADDON_DATA, constants.NOTIFY_FILE)
    try:
        with open(notify_file) as f:
            selected = f.read()
    except IOError:
        utils.log("No installation notification")
    else:
        utils.log("Selected build: {}".format(selected))
        installed = builds.get_installed_build()
        utils.log("Installed build: {}".format(installed))
        if str(installed) == selected:
            msg = "Build {} was installed successfully".format(installed)
            utils.notify(msg)
            utils.log(msg)
        else:
            utils.log("Build {} was not installed".format(selected))
        try:
            os.remove(notify_file)
        except OSError:
            pass # in case file was already deleted
        else:
            utils.log("Removed notification file")


utils.log("Script arguments: {}".format(sys.argv))
if len(sys.argv) > 1:
    if sys.argv[1] == "check":
        check_for_new_build()
    elif sys.argv[1] == "notify":
        notify_installation()
else:
    Main()

