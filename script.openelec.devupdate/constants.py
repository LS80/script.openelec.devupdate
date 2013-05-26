__scriptid__ = 'script.openelec.devupdate'

try:
    VERSION = open('/etc/version').read().rstrip()
except IOError:
    VERSION = '3.0.1'

try:
    ARCH = open('/etc/arch').read().rstrip()
except IOError:
    ARCH = 'RPi.arm'

HEADERS={'User-agent' : "Mozilla/5.0"}