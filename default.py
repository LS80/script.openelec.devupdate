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
from contextlib import closing

import xbmc, xbmcgui, xbmcaddon, xbmcvfs
import requests

from resources.lib import (progress, script_exceptions, utils, builds, openelec,
                           rpi, addon, log, gui, funcs)
from resources.lib.addon import L10n

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
        log.log("Set arch to {}".format(builds.arch))

        if addon.get_bool_setting('set_timeout'):
            builds.timeout = float(addon.get_setting('timeout'))

        self.background = addon.get_bool_setting('background')
        self.verify_files = addon.get_bool_setting('verify_files')
        
        funcs.create_directory(openelec.UPDATE_DIR)

        utils.check_update_files(builds.get_build_from_notify_file(),
                                 force_dialog=True)

        self.installed_build = self.get_installed_build()

        self.select_build()

        utils.remove_update_files()

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

        build_str = utils.format_build(selected_build)
        msg = L10n(32003).format(utils.format_build(self.installed_build),
                                 build_str)

        if selected_build < self.installed_build:
            args = (L10n(32004), L10n(32005), msg)
        elif selected_build > self.installed_build:
            args = (L10n(32001), L10n(32002), msg)
        else:
            msg = L10n(32007).format(build_str)
            args = (L10n(32006), msg, L10n(32008))

        if not utils.yesno(*args):
            sys.exit(0)
            
        self.selected_build = selected_build

    def check_archive(self):
        self.archive = addon.get_bool_setting('archive')
        if self.archive:
            archive_root = addon.get_setting('archive_root')
            self.archive_root = utils.ensure_trailing_slash(archive_root)
            self.archive_tar_path = None
            self.archive_dir = os.path.join(self.archive_root, str(self.selected_source))
            log.log("Archive builds to " + self.archive_dir)
            if not xbmcvfs.exists(self.archive_root):
                log.log("Unable to access archive")
                utils.ok(L10n(32009), L10n(32010).format(self.archive_root), L10n(32011))
                addon.open_settings()
                sys.exit(1)
            elif not xbmcvfs.mkdir(self.archive_dir):
                log.log("Unable to create directory in archive")
                utils.ok(L10n(32009), L10n(32012).format(self.archive_dir), L10n(32013))
                sys.exit(1)

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
                    with progress.FileProgress(L10n(32014), remote_file, self.download_path,
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
                    with progress.DecompressProgress(L10n(32015),
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
                    funcs.remove_file(self.download_path)

            self.maybe_copy_to_archive()
        
            log.log("Moving tar file to " + self.update_tar_path)
            os.renames(self.temp_tar_path, self.update_tar_path)

        addon.set_setting('update_pending', 'true')

    def copy_from_archive(self):
        if self.archive and xbmcvfs.exists(self.archive_tar_path):
            log.log("Skipping download and decompression")

            archive = xbmcvfs.File(self.archive_tar_path)
            try:
                with progress.FileProgress(L10n(32016),
                                           archive, self.update_tar_path, archive.size(),
                                           self.background) as extractor:
                    extractor.start()
            except script_exceptions.Canceled:
                funcs.remove_file(self.tar_path)
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
                with progress.FileProgress(L10n(32017),
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
                    with progress.FileProgress(L10n(32018), ti, temp_image_path, ti.size,
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
                    utils.ok(L10n(32019).format(update_image),
                             self.selected_build.filename,
                             L10n(32020).format(update_image), L10n(32021))
                    utils.remove_update_files()
                    return
                else:
                    log.log("{} md5 is correct".format(update_image))

                funcs.remove_file(temp_image_path)

    def confirm(self):
        funcs.create_notify_file(self.selected_source, self.selected_build)

        build_str = utils.format_build(self.selected_build)
        do_notify = False

        if addon.get_bool_setting('confirm_reboot'):
            if utils.yesno(L10n(32022), " ", L10n(32024).format(build_str)):
                xbmc.restart()
            else:
                do_notify = True
        else:
            if progress.reboot_countdown(
                    L10n(32054), L10n(32025).format(build_str),
                    addon.get_int_setting('reboot_count')):
                xbmc.restart()
                sys.exit()
            else:
                do_notify = True

        if do_notify:
            utils.notify(L10n(32026).format(build_str))


def new_build_check():
    log.log("Checking for a new build")
    
    check_official = addon.get_bool_setting('check_official')
    check_interval = addon.get_int_setting('check_interval')

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

        if addon.get_bool_setting('set_timeout'):
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
            if utils.do_show_dialog():
                log.log("New build {} is available, "
                        "prompting to show build list".format(latest))

                if utils.yesno(
                        addon.name,
                        line1=L10n(32027).format(utils.format_build(latest)),
                        line2=L10n(32028).format(utils.format_build(installed_build)),
                        line3=L10n(32029),
                        autoclose=autoclose_ms):
                    with Main() as main:
                        main.start()
            else:
                utils.notify(L10n(32030).format(utils.format_build(latest)),
                             4000)


log.log_version()
log.log("Script arguments: {}".format(sys.argv))

if addon.get_bool_setting('set_date_format'):
    builds.date_fmt = funcs.strftime_fmt(addon.get_setting('date_format'))
else:
    builds.date_fmt = xbmc.getRegion('dateshort')
log.log("Set date format to {}".format(builds.date_fmt))

if len(sys.argv) > 1:
    if sys.argv[1] == 'checkperiodic':
        if addon.get_bool_setting('check'):
            selected = builds.get_build_from_notify_file()
            if not utils.check_update_files(selected):
                new_build_check()

    elif sys.argv[1] == 'checkonboot':
        if addon.get_bool_setting('check'):
            new_build_check()

    elif sys.argv[1] == 'confirm':
        selected = builds.get_build_from_notify_file()
        if selected:
            installed_build = builds.get_installed_build()
            utils.maybe_confirm_installation(selected, installed_build)
            funcs.remove_notify_file()
        else:
            log.log("No new installation")
else:
    with Main() as main:
        main.start()

