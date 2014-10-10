import os
import sys

# This is required to work around the ImportError exception
# "Failed to import _strptime because the import lock is held by another thread."
import _strptime

import xbmc, xbmcgui, xbmcaddon, xbmcvfs

from resources.lib import constants
from resources.lib import utils
from resources.lib import builds
from resources.lib.progress import restart_countdown

__addon__ = xbmcaddon.Addon(constants.__scriptid__)
__icon__ = __addon__.getAddonInfo('icon')
__dir__ = xbmc.translatePath(__addon__.getAddonInfo('profile'))

init = not sys.argv[0]

if init:
    rpi_config_backup_file = os.path.join(__dir__, constants.RPI_CONFIG_FILE)
    if os.path.exists(rpi_config_backup_file):
        utils.log("Re-enabling overclocking")
        utils.mount_readwrite()
        xbmcvfs.copy(rpi_config_backup_file, constants.RPI_CONFIG_PATH)
        utils.mount_readonly()
        xbmcvfs.delete(rpi_config_backup_file)
        if restart_countdown("Ready to reboot to re-enable overclocking."):
            utils.log("Restarting")
            xbmc.restart()
            sys.exit()
        else:
            utils.log("Restart cancelled")

    update_extlinux_file = os.path.join(__dir__, constants.UPDATE_EXTLINUX)
    if os.path.exists(update_extlinux_file):
        utils.log("Updating extlinux")
        utils.mount_readwrite()
        utils.update_extlinux()
        utils.mount_readonly()
        os.remove(update_extlinux_file)

try:
    installed_build = builds.get_installed_build()
except:
    utils.log("Unable to get installed build so exiting")
    sys.exit(1)

check_enabled = __addon__.getSetting('check') == 'true'
check_onbootonly = __addon__.getSetting('check_onbootonly') == 'true'
check_prompt = int(__addon__.getSetting('check_prompt'))
check_official = __addon__.getSetting('check_official') == 'true'

if init:
    notify_file = os.path.join(__dir__, constants.NOTIFY_FILE)
    try:
        with open(notify_file) as f:
            build = f.read()
    except IOError:
        utils.log("No installation notification")
    else:
        utils.log("Notifying that build {} was installed".format(build))
        if build == str(installed_build):
            utils.notify("Build {} was installed successfully".format(build))
        utils.log("Removing notification file")
        try:
            os.remove(notify_file)
        except OSError:
            pass # in case file was already deleted


    if not check_onbootonly:
        # Start a timer to check for a new build every hour.
        utils.log("Starting build check timer")
        xbmc.executebuiltin("AlarmClock(openelecdevupdate,RunScript({}),03:00:00,silent,loop)".format(__file__))


if check_enabled:
    source = __addon__.getSetting('source')
    if (isinstance(installed_build, builds.Release) and source == "Official Releases"
        and not check_official):
        # Don't do the job of the official auto-update system.
        utils.log("Skipping build check - official release")
    else:
        try:
            if __addon__.getSetting('set_arch') == 'true':
                arch = __addon__.getSetting('arch')
            else:
                arch = constants.ARCH

            subdir = __addon__.getSetting('subdir')
            if source == "Other":
                url = __addon__.getSetting('custom_url')
                build_url = builds.BuildsURL(url, subdir)
            else:
                build_url = builds.sources(arch)[source]
                url = build_url.url

            if __addon__.getSetting('set_timeout') == 'true':
                timeout = int(__addon__.getSetting('timeout'))
            else:
                timeout = None
    
            utils.log("Checking {}".format(url))
            with build_url.extractor() as parser:
                latest = sorted(parser.get_links(arch, timeout), reverse=True)[0]
                if latest > installed_build:
                    if (check_prompt == 1 and xbmc.Player().isPlayingVideo()) or check_prompt == 0:
                        utils.log("Notifying that new build {} is available".format(latest))
                        utils.notify("Build {} is available".format(latest), 7500)
                    else:
                        utils.log("New build {} is available, prompting to show build list".format(latest))
                        if xbmcgui.Dialog().yesno("OpenELEC Dev Update",
                                                  "A more recent build is available:   {}".format(latest),
                                                  "Current build:   {}".format(installed_build),
                                                  "Show builds available to install?"):
                            xbmc.executebuiltin("RunAddon({})".format(constants.__scriptid__))
        except:
            pass
