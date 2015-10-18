''' Module for functions with a dependency on Kodi Python modules '''

from __future__ import division

import os
import sys
import glob
import functools
from urlparse import urlparse

import xbmc, xbmcaddon, xbmcgui

from . import openelec, log, addon, funcs, history, builds


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


def check_update_files(selected, force_dialog=False):
    log.log("Checking for an existing update file")
    if glob.glob(os.path.join(openelec.UPDATE_DIR, '*tar')):
        log.log("An update file is in place")

        if selected:
            build_str = format_build(selected[1])
        else:
            build_str = ""

        msg = "An installation is pending{}{}. ".format(" for " if selected else "",
                                                        build_str)

        if do_show_dialog() or force_dialog:
            if yesno(addon.name,
                     msg,
                     " ",
                     "Reboot now to install the update?"):
                xbmc.restart()
                sys.exit(0)
        else:
            notify(msg + "Please reboot")

        return True
    else:
        return False


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


def notify(msg, time=12000, error=False):
    log.log("Notifying: {}".format(msg))
    if error:
        msg = "[COLOR red]ERROR: {}[/COLOR]".format(msg)
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


def do_show_dialog():
    show = int(addon.get_setting('check_prompt'))
    return show == 2 or (show == 1 and not xbmc.Player().isPlayingVideo())


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

    log.log("Installing command line script {}".format(symlink_path))

    funcs.make_executable(script_path)

    funcs.maybe_create_symlink(script_path, symlink_path)


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


def make_runscript(arg):
    return "RunScript({}, {})".format(addon.info('id'), arg)


def format_build(build):
    return "[COLOR=lightskyblue][B]{}[/COLOR][/B]".format(build)


def setup_build_check():
    xbmc.executebuiltin(make_runscript('checkonboot'))
    if not addon.get_setting('check_onbootonly') == 'true':
        interval = int(addon.get_setting('check_interval'))
        log.log("Starting build check timer for every {:d} hour{}"
                .format(interval, 's' if interval > 1 else ''))
        cmd = ("AlarmClock(devupdatecheck, {}, {:02d}:00:00, silent, loop)".
               format(make_runscript('checkperiodic'), interval))
        xbmc.executebuiltin(cmd)


def maybe_confirm_installation(selected, installed_build):
    source, selected_build = selected
    log.log("Selected build: {}".format(selected_build))
    log.log("Installed build: {}".format(installed_build))

    build_str = format_build(selected_build)
    if installed_build == selected_build:
        msg = "Build {} was installed successfully"
        notify(msg.format(build_str))
        log.log(msg.format(selected_build))

        history.add_install(source, selected_build)
    else:
        msg = "Build {} was not installed"
        notify(msg.format(build_str), error=True)
        log.log(msg.format(selected_build))


def add_custom_sources(sources):
    for suffix in ('', '_2'):
        if addon.get_setting('custom_source_enable' + suffix) == 'true':
            build_type = addon.get_setting('build_type' + suffix)
            try:
                build_type_index = int(build_type)
            except ValueError:
                log.log_error("Invalid build type index '{}'".format(build_type))
                build_type_index = 0

            if build_type_index == 2:
                subdir = addon.get_setting('subdir_preset' + suffix)
                if subdir == 'Other':
                    subdir = addon.get_setting('other_subdir' + suffix)
                custom_name = "Milhouse Builds ({})".format(subdir)
                sources[custom_name] = builds.MilhouseBuildsURL(subdir)
            else:
                custom_name = addon.get_setting('custom_source' + suffix)
                custom_url = addon.get_setting('custom_url' + suffix)
                scheme, netloc = urlparse(custom_url)[:2]
                if not scheme in ('http', 'https') or not netloc:
                    bad_url(custom_url, "Invalid custom source URL")
                else:
                    custom_extractors = (builds.BuildLinkExtractor,
                                         builds.ReleaseLinkExtractor)

                    kwargs = {}
                    if addon.get_setting('custom_subdir_enable' + suffix):
                        kwargs['subdir'] = addon.get_setting('custom_subdir' + suffix)

                    sources[custom_name] = builds.BuildsURL(
                        custom_url, custom_extractors[build_type_index], **kwargs)
