__scriptid__ = 'script.openelec.devupdate'

try:
    ARCH = open('/etc/arch').read().rstrip()
except IOError:
    ARCH = 'RPi.arm'

if ARCH.startswith('Virtual'):
    # This just allows easier testing in a virtual machine
    ARCH = 'RPi.arm'    

HEADERS={'User-agent' : "Mozilla/5.0"}