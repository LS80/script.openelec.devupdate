import re

__scriptid__ = 'script.openelec.devupdate'

try:
    ARCH = open('/etc/arch').read().rstrip()
except IOError:
    ARCH = 'RPi.arm'

if ARCH.startswith('Virtual'):
    # This just allows easier testing in a virtual machine
    ARCH = 'RPi.arm'    

HEADERS = {'User-agent': "Mozilla/5.0"}

NOTIFY_FILE = 'installed_build.txt'

RPI_CONFIG_FILE = '/flash/config.txt'
RPI_CONFIG_BACKUP = '/flash/config.txt' + '.bak'

RPI_OVERCLOCK_SETTINGS = ('arm_freq',
                          'core_freq',
                          'sdram_freq',
                          'over_voltage')

RPI_OVERCLOCK_RE = re.compile(r'^([ \t]*({})[ \t]*=)'.format('|'.join(RPI_OVERCLOCK_SETTINGS)),
                              re.MULTILINE)
