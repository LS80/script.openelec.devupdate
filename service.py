import os
import sys

# This is required to work around the ImportError exception
# "Failed to import _strptime because the import lock is held by another thread."
import _strptime

import xbmc, xbmcgui, xbmcaddon, xbmcvfs

from resources.lib import constants
from resources.lib import utils
from resources.lib.progress import restart_countdown

addon = xbmcaddon.Addon(constants.ADDON_ID)

ADDON_DATA = xbmc.translatePath(addon.getAddonInfo('profile'))


rpi_config_backup_file = os.path.join(ADDON_DATA, constants.RPI_CONFIG_FILE)
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


update_extlinux_file = os.path.join(ADDON_DATA, constants.UPDATE_EXTLINUX)
if os.path.exists(update_extlinux_file):
    utils.log("Updating extlinux")
    utils.mount_readwrite()
    utils.update_extlinux()
    utils.mount_readonly()
    os.remove(update_extlinux_file)


notify_file = os.path.join(ADDON_DATA, constants.NOTIFY_FILE)
try:
    with open(notify_file) as f:
        build = f.read()
except IOError:
    utils.log("No installation notification")
else:
    installed = open('/etc/version').read().rstrip()
    if build == installed:
        utils.log("Notifying that build {} was installed".format(build))
        utils.notify("Build {} was installed successfully".format(build))
    try:
        os.remove(notify_file)
    except OSError:
        pass # in case file was already deleted
    else:
        utils.log("Removed notification file")


check_enabled = addon.getSetting('check') == 'true'
if check_enabled:
    xbmc.executebuiltin("RunScript({},check)".format(constants.ADDON_ID))
    check_onbootonly = addon.getSetting('check_onbootonly') == 'true'
    check_interval = int(addon.getSetting('check_interval'))
    if not check_onbootonly:
        # Start a timer to check for a new build every 3 hours.    
        utils.log("Starting build check timer")
        xbmc.executebuiltin("AlarmClock(openelecdevupdate,RunScript({},check),{:02d}:00:00,silent,loop)".format(constants.ADDON_ID,
                                                                                                                check_interval))
