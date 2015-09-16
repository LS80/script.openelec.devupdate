import os
import sys

# This is required to work around the ImportError exception
# "Failed to import _strptime because the import lock is held by another thread."
import _strptime

import xbmc, xbmcgui, xbmcaddon, xbmcvfs

from resources.lib import constants, utils, openelec, progress


addon = xbmcaddon.Addon(constants.ADDON_ID)

ADDON_DATA = xbmc.translatePath(addon.getAddonInfo('profile'))


rpi_config_backup_file = os.path.join(ADDON_DATA, constants.RPI_CONFIG_FILE)
if os.path.exists(rpi_config_backup_file):
    utils.log("Re-enabling overclocking")
    with openelec.write_context():
        xbmcvfs.copy(rpi_config_backup_file, constants.RPI_CONFIG_PATH)
    xbmcvfs.delete(rpi_config_backup_file)
    if progress.restart_countdown("Ready to reboot to re-enable overclocking."):
        utils.log("Restarting")
        xbmc.restart()
        sys.exit()
    else:
        utils.log("Restart cancelled")


update_extlinux_file = os.path.join(ADDON_DATA, constants.UPDATE_EXTLINUX)
if os.path.exists(update_extlinux_file):
    utils.log("Updating extlinux")
    with openelec.write_context():
        openelec.update_extlinux()
    os.remove(update_extlinux_file)


xbmc.executebuiltin("RunScript({},confirm)".format(constants.ADDON_ID))

check_enabled = addon.getSetting('check') == 'true'
if check_enabled:
    xbmc.executebuiltin("RunScript({},check)".format(constants.ADDON_ID))
    check_onbootonly = addon.getSetting('check_onbootonly') == 'true'
    check_interval = int(addon.getSetting('check_interval'))
    if not check_onbootonly:
        # Start a timer to check for a new build every 3 hours.    
        utils.log("Starting build check timer")
        xbmc.executebuiltin("AlarmClock(openelecdevupdate,"
            "RunScript({},check),{:02d}:00:00,silent,loop)".format(constants.ADDON_ID,
                                                                   check_interval))

utils.install_cmdline_script()
