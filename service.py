''' Run all the jobs which need to be run automatically '''

# This is required to work around the ImportError exception
# "Failed to import _strptime because the import lock is held by another thread."
import _strptime

import xbmc

from resources.lib import utils, rpi, funcs, log

log.log_version()

rpi.maybe_restore_config()

funcs.maybe_update_extlinux()

# Need to call out to the main script here
# because sys.path is only set when running the main script
# and the builds module needs to import requests
xbmc.executebuiltin(utils.make_runscript('confirm'))

utils.setup_build_check()

utils.install_cmdline_script()
