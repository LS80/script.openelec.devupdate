import os
import re

import xbmcvfs

import openelec, addon

CONFIG_FILE = 'config.txt'
CONFIG_PATH = '/flash/' + CONFIG_FILE

OVERCLOCK_SETTINGS = ('arm_freq',
                      'core_freq',
                      'sdram_freq',
                      'over_voltage.*')

OVERCLOCK_RE = re.compile(r'^([ \t]*({})[ \t]*=)'.format('|'.join(OVERCLOCK_SETTINGS)),
                          re.MULTILINE)


def maybe_disable_overclock():
    if (openelec.ARCH.startswith('RPi') and
        os.path.isfile(CONFIG_PATH) and
        addon.get_setting('disable_overclock') == 'true'):

        with open(CONFIG_PATH, 'r') as a:
            config = a.read()

        if OVERCLOCK_RE.search(config):

            xbmcvfs.copy(CONFIG_PATH,
                         os.path.join(addon.data_path, CONFIG_FILE))

            def repl(m):
                return '#' + m.group(1)

            with openelec.write_context(), open(CONFIG_PATH, 'w') as b:
                b.write(re.sub(OVERCLOCK_RE, repl, config))
