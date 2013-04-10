import re

try:
    VERSION = open('/etc/version').read()
except IOError:
    VERSION = '1.0.0'

try:
    CURRENT_BUILD = int(re.search('-r(\d+)', VERSION).group(1))
except AttributeError:
    CURRENT_BUILD = VERSION.rstrip()

try:
    ARCH = open('/etc/arch').read().rstrip()
except IOError:
    ARCH = 'RPi.arm'

HEADERS={'User-agent' : "Mozilla/5.0"}