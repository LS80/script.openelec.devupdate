import os
import re
import sys

import xbmc, xbmcvfs

from . import openelec, addon, log, progress
from .addon import L10n

CONFIG_FILE = 'config.txt'
CONFIG_PATH = '/flash/' + CONFIG_FILE
CONFIG_BACKUP_PATH = os.path.join(addon.data_path, CONFIG_FILE)

OVERCLOCK_SETTINGS = ('arm_freq',
                      'core_freq',
                      'sdram_freq',
                      'over_voltage.*')

OVERCLOCK_RE = re.compile(r'^([ \t]*({})[ \t]*=)'.format('|'.join(OVERCLOCK_SETTINGS)),
                          re.MULTILINE)


def maybe_restore_config():
    if os.path.exists(CONFIG_BACKUP_PATH):
        log.log("Re-enabling overclocking")
        with openelec.write_context():
            xbmcvfs.copy(CONFIG_BACKUP_PATH, CONFIG_PATH)
        xbmcvfs.delete(CONFIG_BACKUP_PATH)
        if progress.reboot_countdown(L10n(32054), L10n(32040),
                                     addon.get_int_setting('reboot_count')):
            log.log("Restarting")
            xbmc.restart()
            sys.exit()
        else:
            log.log("Restart cancelled")


def maybe_disable_overclock():
    if (openelec.ARCH.startswith('RPi') and
        os.path.isfile(CONFIG_PATH) and
        addon.get_bool_setting('disable_overclock')):

        with open(CONFIG_PATH, 'r') as a:
            config = a.read()

        if OVERCLOCK_RE.search(config):

            xbmcvfs.copy(CONFIG_PATH,
                         os.path.join(addon.data_path, CONFIG_FILE))

            def repl(m):
                return '#' + m.group(1)

            with openelec.write_context(), open(CONFIG_PATH, 'w') as b:
                b.write(re.sub(OVERCLOCK_RE, repl, config))
