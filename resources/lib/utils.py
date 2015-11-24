''' Module for functions with a dependency on Kodi Python modules '''

from __future__ import division

import os
import sys
import functools
from urlparse import urlparse

import xbmc, xbmcaddon, xbmcgui

from . import openelec, log, addon, funcs, history, builds
from .addon import L10n


ok = xbmcgui.Dialog().ok
yesno = xbmcgui.Dialog().yesno
notification = xbmcgui.Dialog().notification


def connection_error(msg):
    ok(L10n(32041), msg, L10n(32042))

    
def bad_url(url, msg=L10n(32043)):
    ok(L10n(32044), msg, url, L10n(32045))

    
def url_error(url, msg):
    log.log_exception()
    ok(L10n(32044), msg, url, L10n(32046))


def write_error(path, msg):
    log.log_exception()
    ok(L10n(32047), msg, path, L10n(32048))
    addon.open_settings()


def decompress_error(path, msg):
    log.log_exception()
    ok(L10n(32049), L10n(32050), " ", msg)


def check_update_files(selected, force_dialog=False):
    log.log("Checking for an existing update file")
    if funcs.update_files():
        log.log("An update file is in place")

        if selected:
            build_str = format_build(selected[1])
            msg = L10n(32052).format(build_str)
        else:
            build_str = ""
            msg = L10n(32053)

        if do_show_dialog() or force_dialog:
            if yesno(addon.name, msg, " ", L10n(32055)):
                xbmc.restart()
                sys.exit(0)
        else:
            notify(" ".join((msg, L10n(32056))))

        return True
    else:
        return False


def remove_update_files():
    return all(funcs.remove_file(tar) for tar in funcs.update_files())


def get_arch():
    if addon.get_bool_setting('set_arch'):
        return addon.get_setting('arch')
    else:
        return openelec.ARCH


def notify(msg, time=12000, error=False):
    log.log("Notifying: {}".format(msg))
    if error:
        msg = "[COLOR red]{}[/COLOR]".format(L10n(32060)).format(msg)
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
    show = addon.get_int_setting('check_prompt')
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
        addon.get_bool_setting('update_extlinux')):
        funcs.schedule_extlinux_update()


def maybe_run_backup():
    backup = addon.get_int_setting('backup')
    if backup == 0:
        do_backup = False
    elif backup == 1:
        do_backup = yesno(L10n(32061), L10n(32062), L10n(32063))
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
    if not addon.get_bool_setting('check_onbootonly'):
        interval = addon.get_int_setting('check_interval')
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
        msg = L10n(32064)
        notify(msg.format(build_str))
        log.log(msg.format(selected_build))

        history.add_install(source, selected_build)
    else:
        msg = L10n(32065)
        notify(msg.format(build_str), error=True)
        log.log(msg.format(selected_build))


def add_custom_sources(sources):
    for suffix in ('', '_2', '_3'):
        if addon.get_bool_setting('custom_source_enable' + suffix):
            build_type = addon.get_setting('build_type' + suffix)
            try:
                build_type_index = int(build_type)
            except ValueError:
                log.log_error("Invalid build type index '{}'".format(build_type))
                build_type_index = 0

            if build_type_index == 2:
                subdir = addon.get_setting('subdir_preset' + suffix)
                if subdir == L10n(32128):
                    subdir = addon.get_setting('other_subdir' + suffix)
                custom_name = "Milhouse Builds ({})".format(subdir)
                sources[custom_name] = builds.MilhouseBuildsURL(subdir)
            elif build_type_index < 2:
                custom_name = addon.get_setting('custom_source' + suffix)
                custom_url = addon.get_setting('custom_url' + suffix)
                scheme, netloc = urlparse(custom_url)[:2]
                if not scheme in ('http', 'https') or not netloc:
                    bad_url(custom_url, L10n(32066))
                    continue

                custom_extractors = (builds.BuildLinkExtractor,
                                     builds.ReleaseLinkExtractor)

                kwargs = {}
                if addon.get_setting('custom_subdir_enable' + suffix):
                    kwargs['subdir'] = addon.get_setting('custom_subdir' + suffix)

                sources[custom_name] = builds.BuildsURL(
                    custom_url, extractor=custom_extractors[build_type_index], **kwargs)
            elif build_type_index == 3:
                sources["DarkAngel2401 Dual Audio Builds"] = builds.dual_audio_builds
