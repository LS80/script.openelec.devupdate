''' Module for functions which also work outside of Kodi '''

import os
import sys
import stat
import glob

import log, openelec


TEMP_DIR = os.path.expanduser('~')

UPDATE_EXTLINUX_FILE = os.path.join(TEMP_DIR, '.update_extlinux')
NOTIFY_FILE = os.path.join(TEMP_DIR, '.installed_build')

STRFTIME_FMTS = [('YYYY', '%Y'),
                 ('YY', '%y'),
                 ('MMMM', '%B'),
                 ('MMM', '%b'),
                 ('MM', '%m'),
                 ('M', '%-m'),
                 ('DD', '%d'),
                 ('D', '%-d')]


def strftime_fmt(date_fmt):
    for key, fmt in STRFTIME_FMTS:
        date_fmt = date_fmt.replace(key, fmt)
    return date_fmt


def size_fmt(num):
    for s, f in (('bytes', '{0:.0f}'), ('KB', '{0:.1f}'), ('MB', '{0:.1f}')):
        if num < 1024.0:
            return (f + " {1}").format(num, s)
        num /= 1024.0


def add_deps_to_path():
    addons = os.path.join(os.path.expanduser('~'), '.kodi', 'addons')
    if os.path.isdir(addons):
        for module in ('requests', 'beautifulsoup4', 'html2text'):
            path = os.path.join(addons, 'script.module.' + module, 'lib')
            sys.path.append(path)


def create_empty_file(path):
    open(path, 'w').close()


def create_notify_file(source, build):
    with open(NOTIFY_FILE, 'w') as f:
        f.write('\n'.join((str(source), repr(build))))


def remove_notify_file():
    remove_file(NOTIFY_FILE)


def read_notify_file():
    try:
        with open(NOTIFY_FILE) as f:
            return f.read().splitlines()
    except (IOError, ValueError):
        return None


def schedule_extlinux_update():
    create_empty_file(UPDATE_EXTLINUX_FILE)


def maybe_update_extlinux():
    if os.path.isfile(UPDATE_EXTLINUX_FILE):
        log.log("Updating extlinux")
        with openelec.write_context():
            openelec.update_extlinux()
        remove_file(UPDATE_EXTLINUX_FILE)


@log.with_logging("Created directory {}", log_exc=False)
def create_directory(path):
    os.mkdir(path)


@log.with_logging("Removed file", "Could not remove file")
def remove_file(file_path):
    log.log("Removing {}".format(file_path))
    try:
        os.remove(file_path)
    except OSError:
        return False
    else:
        return True


@log.with_logging(msg_error="Unable to make executable")
def make_executable(path):
    os.chmod(path, stat.S_IXUSR|stat.S_IRUSR|stat.S_IWUSR)


@log.with_logging(msg_error="Unable to create symbolic link")
def maybe_create_symlink(path, symlink_path):
    if not(os.path.islink(symlink_path) and
           os.path.realpath(symlink_path) == path):
        try:
            os.remove(symlink_path)
        except:
            pass
        os.symlink(path, symlink_path)


def update_files():
    return glob.glob(os.path.join(openelec.UPDATE_DIR, '*tar'))
