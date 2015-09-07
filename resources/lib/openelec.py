import os
import glob
import subprocess


def mount_readwrite():
    subprocess.call(['mount', '-o', 'rw,remount', '/flash'])


def mount_readonly():
    subprocess.call(['mount', '-o', 'ro,remount', '/flash'])


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
    if system_size_bytes >= 384 * 1024*1024:
        return True
    else:
        return False
