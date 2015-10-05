''' Module for functions with a dependency on Kodi Python modules '''

from __future__ import division

import os
import sys
import glob
import functools

import xbmc, xbmcaddon, xbmcgui

from . import openelec, log, addon, funcs, history


ok = xbmcgui.Dialog().ok
yesno = xbmcgui.Dialog().yesno
notification = xbmcgui.Dialog().notification

def connection_error(msg):
    ok("Connection Error", msg,
       "Please check you have a connection to the internet.")

    
def bad_url(url, msg="URL not found."):
    ok("URL Error", msg, url, "Please check the URL.")

    
def url_error(url, msg):
    log.log_exception()
    ok("URL Error", msg, url, "Please check the log file.")

    
def write_error(path, msg):
    log.log_exception()
    ok("Write Error", msg, path,
       "Check the download directory in the addon settings.")
    addon.open_settings()

    
def decompress_error(path, msg):
    log.log_exception()
    ok("Decompression Error",
       "An error occurred during decompression:",
       " ", msg)


def check_update_files(selected):
    # Check if an update file is already in place.
    if glob.glob(os.path.join(openelec.UPDATE_DIR, '*tar')):
        if selected:
            s = " for "
            _, selected_build = selected
        else:
            s = selected_build = ""

        msg = ("An installation is pending{}"
               "[COLOR=lightskyblue][B]{}[/B][/COLOR].").format(s, selected_build)
        if yesno("Confirm reboot",
                 msg,
                 "Reboot now to install the update",
                 "or continue to select another build.",
                 "Continue",
                 "Reboot"):
            xbmc.restart()
            sys.exit(0)
        else:
            remove_update_files()


def remove_update_files():
    tar_update_files = glob.glob(os.path.join(openelec.UPDATE_DIR, '*tar'))
    success = all(funcs.remove_file(tar) for tar in tar_update_files)

    if success:
        addon.set_setting('update_pending', 'false')
    return success


def get_arch():
    if addon.get_setting('set_arch') == 'true':
        return addon.get_setting('arch')
    else:
        return openelec.ARCH


def notify(msg, time=12000):
    notification(addon.name, msg, addon.icon_path, time)

    
def showbusy(f):
    @functools.wraps(f)
    def busy_wrapper(*args, **kwargs):
        xbmc.executebuiltin("ActivateWindow(busydialog)")
        try:
            return f(*args, **kwargs)
        finally:
            xbmc.executebuiltin("Dialog.Close(busydialog)")
    return busy_wrapper


def build_check_prompt():
    check_prompt = int(addon.get_setting('check_prompt'))
    return check_prompt == 2 or (check_prompt == 1 and not xbmc.Player().isPlayingVideo())


def ensure_trailing_slash(path):
    return path if path.endswith('/') else path + '/'


@log.with_logging(msg_error="Unable to check if another instance is running")
def is_running():
    running = xbmcgui.Window(10000).getProperty('DevUpdateRunning') == 'True'
    log.log("Another instance is running" if running else "No other instance is running")
    return running


@log.with_logging("Set running flag", "Unable to set running flag")
def set_running():
    xbmcgui.Window(10000).setProperty('DevUpdateRunning', 'True')


@log.with_logging("Cleared running flag", "Unable to clear running flag")
def set_not_running():
    xbmcgui.Window(10000).clearProperty('DevUpdateRunning')


def install_cmdline_script():
    """ Creates a symbolic link to the command line download script
    in the root user home directory. The script can then be invoked
    by running:

        ./devupdate
    """

    SCRIPT_NAME = "download.py"
    script_path = os.path.join(addon.src_path, SCRIPT_NAME)

    SYMLINK_NAME = "devupdate"
    symlink_path = os.path.join(os.path.expanduser('~'), SYMLINK_NAME)

    funcs.make_executable(script_path)

    funcs.create_symlink(script_path, symlink_path)


def maybe_schedule_extlinux_update():
    if (not openelec.ARCH.startswith('RPi') and
        addon.get_setting('update_extlinux') == 'true'):
        funcs.schedule_extlinux_update()


def maybe_run_backup():
    backup = int(addon.get_setting('backup'))
    if backup == 0:
        do_backup = False
    elif backup == 1:
        do_backup = yesno("Backup", "Run Backup now?", "This is recommended")
        log.log("Backup requested")
    elif backup == 2:
        do_backup = True
        log.log("Backup always")

    if do_backup:
        xbmc.executebuiltin('RunScript(script.xbmcbackup, mode=backup)', True)
        xbmc.sleep(10000)
        window = xbmcgui.Window(10000)
        while (window.getProperty('script.xbmcbackup.running') == 'true'):
            xbmc.sleep(5000)


def start_new_build_check_timer():
    if addon.get_setting('check') == 'true':
        xbmc.executebuiltin("RunScript({},check)".format(addon.info('id')))
        check_interval = int(addon.get_setting('check_interval'))
        if not addon.get_setting('check_onbootonly') == 'true':
            log.log("Starting build check timer")
            xbmc.executebuiltin("AlarmClock(openelecdevupdate,"
                "RunScript({},check),{:02d}:00:00,silent,loop)".format(addon.info('id'),
                                                                       check_interval))


def maybe_confirm_installation(selected, installed_build):
    if selected:
        source, selected_build = selected

        log.log("Selected build: {}".format(selected_build))

        log.log("Installed build: {}".format(installed_build))
        if installed_build == selected_build:
            msg = "Build {} was installed successfully".format(installed_build)
            notify(msg)
            log.log(msg)

            history.add_install(source, selected_build)
        else:
            msg = "Build {} was not installed".format(selected_build)
            notify("[COLOR red]ERROR: {}[/COLOR]".format(msg))
            log.log(msg)

            remove_update_files()
    else:
        log.log("No installation notification")

    funcs.remove_notify_file()
