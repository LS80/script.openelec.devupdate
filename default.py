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
############################################################################

from __future__ import division

import os
import sys
import tarfile
import glob
from contextlib import closing

import xbmc, xbmcgui, xbmcaddon, xbmcvfs
import requests

from resources.lib import (constants, progress, script_exceptions,
                           utils, builds, openelec, history, rpi,
                           addon, log, gui)


TEMP_PATH = xbmc.translatePath("special://temp/")


class Main(object):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        already_running = exc_type is script_exceptions.AlreadyRunning

        if not already_running:
            utils.set_not_running()

        return already_running

    def start(self):
        if utils.is_running():
            raise script_exceptions.AlreadyRunning

        utils.set_running()
        log.log("Starting")

        builds.arch = utils.get_arch()

        if addon.get_setting('set_timeout') == 'true':
            builds.timeout = float(addon.get_setting('timeout'))

        utils.create_directory(openelec.UPDATE_DIR)

        check_update_files()

        self.background = addon.get_setting('background') == 'true'
        self.verify_files = addon.get_setting('verify_files') == 'true'
        
        self.installed_build = self.get_installed_build()

        self.select_build()

        self.check_archive()

        self.maybe_download()

        self.maybe_verify()

        rpi.maybe_disable_overclock()

        utils.maybe_schedule_extlinux_update()

        utils.maybe_run_backup()

        self.confirm()

    def get_installed_build(self):        
        try:
            return builds.get_installed_build()
        except requests.ConnectionError as e:
            utils.connection_error(str(e))
            sys.exit(1)

    def check_archive(self):
        self.archive = addon.get_setting('archive') == 'true'
        if self.archive:
            archive_root = addon.get_setting('archive_root')
            self.archive_root = utils.ensure_trailing_slash(archive_root)
            self.archive_tar_path = None
            self.archive_dir = os.path.join(self.archive_root, str(self.selected_source))
            log.log("Archive builds to " + self.archive_dir)
            if not xbmcvfs.exists(self.archive_root):
                log.log("Unable to access archive")
                utils.ok("Directory Error",
                         "{} is not accessible.".format(self.archive_root),
                         "Check the archive directory in the addon settings.")
                addon.open_settings()
                sys.exit(1)
            elif not xbmcvfs.mkdir(self.archive_dir):
                log.log("Unable to create directory in archive")
                utils.ok("Directory Error",
                         "Unable to create {}.".format(self.archive_dir),
                         "Check the archive directory permissions.")
                sys.exit(1)

    def select_build(self):
        build_select = gui.BuildSelectDialog(self.installed_build)
        build_select.doModal()
        
        self.selected_source = build_select.selected_source
        addon.set_setting('source_name', self.selected_source)
        log.log("Selected source: " + str(self.selected_source))
        
        if not build_select:
            log.log("No build selected")
            sys.exit(0)

        selected_build = build_select.selected_build
        log.log("Selected build: " + str(selected_build))
    
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
        if not utils.yesno(*args):
            sys.exit(0)
            
        self.selected_build = selected_build

    def maybe_download(self):
        try:
            remote_file = self.selected_build.remote_file()
        except requests.RequestException as e:
            utils.url_error(self.selected_build.url, str(e))
            sys.exit(1)

        filename = self.selected_build.filename
        tar_name = self.selected_build.tar_name
        size = self.selected_build.size
        
        self.download_path = os.path.join(TEMP_PATH, filename)
        self.temp_tar_path = os.path.join(TEMP_PATH, tar_name)
        self.update_tar_path = os.path.join(openelec.UPDATE_DIR, tar_name)
        if self.archive:
            self.archive_tar_path = os.path.join(self.archive_dir, tar_name)
        
        if not self.copy_from_archive():
            if (os.path.isfile(self.download_path) and
                    os.path.getsize(self.download_path) == size):
                    # Skip the download if the file exists with the correct size.
                log.log("Skipping download")
            else:
                try:
                    log.log("Starting download of {} to {}".format(self.selected_build.url,
                                                                   self.download_path))
                    with progress.FileProgress("Downloading", remote_file, self.download_path,
                                               size, self.background) as downloader:
                        downloader.start()
                    log.log("Completed download")
                except script_exceptions.Canceled:
                    sys.exit(0)
                except requests.RequestException as e:
                    utils.url_error(self.selected_build.url, str(e))
                    sys.exit(1)
                except script_exceptions.WriteError as e:
                    utils.write_error(self.download_path, str(e))
                    sys.exit(1)

            if self.selected_build.compressed:
                try:
                    bf = open(self.download_path, 'rb')
                    log.log("Starting decompression of " + self.download_path)
                    with progress.DecompressProgress("Decompressing",
                                                     bf, self.temp_tar_path, size,
                                                     self.background) as decompressor:
                        decompressor.start()
                    log.log("Completed decompression")
                except script_exceptions.Canceled:
                    sys.exit(0)
                except script_exceptions.WriteError as e:
                    utils.write_error(self.temp_tar_path, str(e))
                    sys.exit(1)
                except script_exceptions.DecompressError as e:
                    utils.decompress_error(self.download_path, str(e))
                    sys.exit(1)
                finally:
                    utils.remove_file(self.download_path)

            self.maybe_copy_to_archive()
        
            log.log("Moving tar file to " + self.update_tar_path)
            os.rename(self.temp_tar_path, self.update_tar_path)

        addon.set_setting('update_pending', 'true')

    def copy_from_archive(self):
        if self.archive and xbmcvfs.exists(self.archive_tar_path):
            log.log("Skipping download and decompression")

            archive = xbmcvfs.File(self.archive_tar_path)
            try:
                with progress.FileProgress("Retrieving tar file from archive",
                                           archive, self.update_tar_path, archive.size(),
                                           self.background) as extractor:
                    extractor.start()
            except script_exceptions.Canceled:
                utils.remove_file(self.tar_path)
                sys.exit(0)
            except script_exceptions.WriteError:
                sys.exit(1)
            return True
        return False

    def maybe_copy_to_archive(self):
        if self.archive and not xbmcvfs.exists(self.archive_tar_path):
            log.log("Archiving tar file to {}".format(self.archive_tar_path))

            tar = open(self.temp_tar_path)
            size = os.path.getsize(self.temp_tar_path)

            try:
                with progress.FileProgress("Copying to archive",
                                           tar, self.archive_tar_path, size,
                                           self.background) as extractor:
                    extractor.start()
            except script_exceptions.Canceled:
                log.log("Archive copy canceled")
                xbmcvfs.delete(self.archive_tar_path)
            except script_exceptions.WriteError as e:
                utils.write_error(self.archive_tar_path, str(e))
                xbmcvfs.delete(self.archive_tar_path)

    def maybe_verify(self):
        if not self.verify_files:
            return

        log.log("Verifying update file")
        with closing(tarfile.open(self.update_tar_path, 'r')) as tf:
            tar_names = tf.getnames()

            for update_image in openelec.UPDATE_IMAGES:
                path_in_tar = next(name for name in tar_names
                                   if name.endswith(os.path.join('target', update_image)))
                ti = tf.extractfile(path_in_tar)
                temp_image_path = os.path.join(TEMP_PATH, update_image)
                try:
                    with progress.FileProgress("Verifying", ti, temp_image_path, ti.size,
                                               self.background) as extractor:
                        extractor.start()
                    log.log("Extracted " + temp_image_path)
                except script_exceptions.Canceled:
                    return
                except script_exceptions.WriteError as e:
                    utils.write_error(temp_image_path, str(e))
                    return

                md5sum = tf.extractfile(path_in_tar + '.md5').read().split()[0]
                log.log("{}.md5 file = {}".format(update_image, md5sum))
        
                if not progress.md5sum_verified(md5sum, temp_image_path,
                                                self.background):
                    log.log("{} md5 mismatch!".format(update_image))
                    utils.ok("{} md5 mismatch".format(update_image),
                             "The {} image from".format(update_image),
                             self.selected_build.filename,
                             "is corrupt. The update file will be removed.")
                    utils.remove_update_files()
                    return
                else:
                    log.log("{} md5 is correct".format(update_image))

                utils.remove_file(temp_image_path)

    def confirm(self):
        with open(constants.NOTIFY_FILE, 'w') as f:
            f.write('\n'.join((self.selected_source, repr(self.selected_build))))

        if addon.get_setting('confirm_reboot') == 'true':
            if utils.yesno(
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


def check_update_files():
    # Check if an update file is already in place.
    if glob.glob(os.path.join(openelec.UPDATE_DIR, '*tar')):
        selected = builds.get_build_from_file(constants.NOTIFY_FILE)
        if selected:
            s = " for "
            _, selected_build = selected
        else:
            s = selected_build = ""

        msg = ("An installation is pending{}"
               "[COLOR=lightskyblue][B]{}[/B][/COLOR].").format(s, selected_build)
        if utils.yesno("Confirm reboot",
                       msg,
                       "Reboot now to install the update",
                       "or continue to select another build.",
                       "Continue",
                       "Reboot"):
            xbmc.restart()
            sys.exit(0)
        else:
            utils.remove_update_files()


def check_for_new_build():
    log.log("Checking for a new build")
    
    check_official = addon.get_setting('check_official') == 'true'
    check_interval = int(addon.get_setting('check_interval'))

    autoclose_ms = check_interval * 3540000 # check interval in ms - 1 min
    
    try:
        installed_build = builds.get_installed_build()
    except:
        log.log("Unable to get installed build so exiting")
        sys.exit(1)

    source = addon.get_setting('source_name')
    if (isinstance(installed_build, builds.Release) and source == "Official Releases"
        and not check_official):
        # Don't do the job of the official auto-update system.
        log.log("Skipping build check - official release")
    else:
        builds.arch = utils.get_arch()

        if addon.get_setting('set_timeout') == 'true':
            builds.timeout = float(addon.get_setting('timeout'))

        build_sources = builds.sources()
        try:
            build_url = build_sources[source]
        except KeyError:
            log.log("{} is not a valid source".format(source))
            return

        log.log("Checking {}".format(build_url.url))

        latest = builds.latest_build(source)
        if latest and latest > installed_build:
            if utils.build_check_prompt():
                log.log("New build {} is available, "
                        "prompting to show build list".format(latest))

                if utils.yesno(
                        addon.name,
                        line1="A more recent build is available:"
                        "   [COLOR lightskyblue][B]{}[/B][/COLOR]".format(latest),
                        line2="Current build:"
                        "   [COLOR lightskyblue][B]{}[/B][/COLOR]".format(installed_build),
                        line3="Show builds available to install?",
                        autoclose=autoclose_ms):
                    with Main() as main:
                        main.start()
            else:
                log.log("Notifying that new build {} is available".format(latest))
                utils.notify("Build {} is available".format(latest), 4000)


def confirm_installation():
    selected = builds.get_build_from_file(constants.NOTIFY_FILE)
    if selected:
        source, selected_build = selected

        log.log("Selected build: {}".format(selected_build))
        installed_build = builds.get_installed_build()
        log.log("Installed build: {}".format(installed_build))
        if installed_build == selected_build:
            msg = "Build {} was installed successfully".format(installed_build)
            utils.notify(msg)
            log.log(msg)

            history.add_install(source, selected_build)
        else:
            msg = "Build {} was not installed".format(selected_build)
            utils.notify("[COLOR red]ERROR: {}[/COLOR]".format(msg))
            log.log(msg)

            utils.remove_update_files()
    else:
        log.log("No installation notification")

    utils.remove_file(constants.NOTIFY_FILE)


log.log("Script arguments: {}".format(sys.argv))
if len(sys.argv) > 1:
    if sys.argv[1] == 'check':
        check_for_new_build()
    elif sys.argv[1] == 'confirm':
        confirm_installation()
    elif sys.argv[1] == 'cancel':
        success = utils.remove_update_files()
        if success:
            utils.notify("Deleted update file")
        else:
            utils.notify("Update file not deleted")
else:
    with Main() as main:
        main.start()

