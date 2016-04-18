import os
import glob
import subprocess
from contextlib import contextmanager


OS_RELEASE = dict(line.strip().replace('"', '').split('=')
                  for line in open('/etc/os-release'))

try:
    ARCH = OS_RELEASE['OPENELEC_ARCH']
except KeyError:
    # Enables testing on non OpenELEC machines
    ARCH = 'RPi.arm'

UPDATE_DIR = os.path.join(os.path.expanduser('~'), '.update')
if OS_RELEASE['NAME'] not in ["OpenELEC", "LibreELEC"]:
    try:
        import xbmc
    except ImportError:
        # Enables testing standalone script outside Kodi
        UPDATE_DIR = os.path.expanduser('~')
    else:
        # Enables testing in non OpenELEC Kodi
        UPDATE_DIR = xbmc.translatePath("special://temp/")

UPDATE_IMAGES = ('SYSTEM', 'KERNEL')

def dist():
    dist = OS_RELEASE['NAME']
    if dist in ("LibreELEC", "OpenELEC"):
        return dist.lower()
    else:
        return "libreelec"


def mount_readwrite():
    subprocess.check_call(['mount', '-o', 'rw,remount', '/flash'])


def mount_readonly():
    subprocess.call(['mount', '-o', 'ro,remount', '/flash'])


@contextmanager
def write_context():
    try:
        mount_readwrite()
    except subprocess.CalledProcessError:
        pass
    else:
        try:
            yield
        finally:
            mount_readonly()


def update_extlinux():
    subprocess.call(['/usr/bin/extlinux', '--update', '/flash'])


def debug_system_partition():
    try:
        partition = os.path.basename(os.readlink('/dev/disk/by-label/System'))
    except OSError:
        return False    
    
    try:
        size_path = glob.glob('/sys/block/*/{}/size'.format(partition))[0]
    except IndexError:
        return False
    
    system_size_bytes = int(open(size_path).read()) * 512
    return system_size_bytes >= 384 * 1024*1024
