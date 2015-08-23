import re
import os

ADDON_ID = "script.openelec.devupdate"

OS_RELEASE = dict(line.strip().replace('"', '').split('=')
                  for line in open('/etc/os-release'))

try:
    ARCH = OS_RELEASE['OPENELEC_ARCH']
except KeyError:
    # Enables testing on non OpenELEC machines
    ARCH = 'RPi.arm'

UPDATE_DIR = os.path.join(os.path.expanduser('~'), '.update')
if OS_RELEASE['NAME'] != "OpenELEC":
    try:
        import xbmc
    except ImportError:
        # Enables testing standalone script
        UPDATE_DIR = os.path.expanduser('~')
    else:
        # Enables testing on non OpenELEC machines
        UPDATE_DIR = xbmc.translatePath("special://temp/")

if ARCH == 'ATV.i386':  
    UPDATE_IMAGES = ('SYSTEM', 'MACH_KERNEL')
else:
    UPDATE_IMAGES = ('SYSTEM', 'KERNEL')

UPDATE_FILES = UPDATE_IMAGES + tuple(f + '.md5' for f in UPDATE_IMAGES)
UPDATE_PATHS = tuple(os.path.join(UPDATE_DIR, f) for f in UPDATE_FILES)

NOTIFY_FILE = 'installed_build.txt'

UPDATE_EXTLINUX = 'update_extlinux'

RPI_CONFIG_FILE = 'config.txt'
RPI_CONFIG_PATH = '/flash/' + RPI_CONFIG_FILE

RPI_OVERCLOCK_SETTINGS = ('arm_freq',
                          'core_freq',
                          'sdram_freq',
                          'over_voltage.*')

RPI_OVERCLOCK_RE = re.compile(r'^([ \t]*({})[ \t]*=)'.format('|'.join(RPI_OVERCLOCK_SETTINGS)),
                              re.MULTILINE)
