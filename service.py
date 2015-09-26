import os
import sys

# This is required to work around the ImportError exception
# "Failed to import _strptime because the import lock is held by another thread."
import _strptime

import xbmc, xbmcgui, xbmcaddon, xbmcvfs

from resources.lib import constants, utils, openelec, progress, addon, rpi, log


rpi_config_backup_file = os.path.join(addon.data_path, rpi.CONFIG_FILE)
if os.path.exists(rpi_config_backup_file):
    log.log("Re-enabling overclocking")
    with openelec.write_context():
        xbmcvfs.copy(rpi_config_backup_file, rpi.CONFIG_PATH)
    xbmcvfs.delete(rpi_config_backup_file)
    if progress.restart_countdown("Ready to reboot to re-enable overclocking."):
        log.log("Restarting")
        xbmc.restart()
        sys.exit()
    else:
        log.log("Restart cancelled")


update_extlinux_file = os.path.join(addon.data_path, constants.UPDATE_EXTLINUX_FILE)
if os.path.exists(update_extlinux_file):
    log.log("Updating extlinux")
    with openelec.write_context():
        openelec.update_extlinux()
    os.remove(update_extlinux_file)


xbmc.executebuiltin("RunScript({},confirm)".format(addon.info('id')))

check_enabled = addon.get_setting('check') == 'true'
if check_enabled:
    xbmc.executebuiltin("RunScript({},check)".format(addon.info('id')))
    check_onbootonly = addon.get_setting('check_onbootonly') == 'true'
    check_interval = int(addon.get_setting('check_interval'))
    if not check_onbootonly:
        # Start a timer to check for a new build every 3 hours.    
        log.log("Starting build check timer")
        xbmc.executebuiltin("AlarmClock(openelecdevupdate,"
            "RunScript({},check),{:02d}:00:00,silent,loop)".format(addon.info('id'),
                                                                   check_interval))

utils.install_cmdline_script()
