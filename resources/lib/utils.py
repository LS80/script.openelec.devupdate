from __future__ import division

import os
import sys
import glob
import functools
import stat

import xbmc, xbmcaddon, xbmcgui

import constants

addon = xbmcaddon.Addon(constants.ADDON_ID)

ADDON_NAME = addon.getAddonInfo('name')
ADDON_VERSION = xbmc.translatePath(addon.getAddonInfo('version'))
ICON_PATH = addon.getAddonInfo('icon')
ADDON_PATH = xbmc.translatePath(addon.getAddonInfo('path'))


def log(txt, level=xbmc.LOGNOTICE):
    if addon.getSetting('debug') == 'true':
        msg = '{} v{}: {}'.format(ADDON_NAME,
                                  ADDON_VERSION, txt)
        xbmc.log(msg, level)

log_error = functools.partial(log, level=xbmc.LOGERROR)

def log_exception():
    import traceback
    log("".join(traceback.format_exception(*sys.exc_info())), xbmc.LOGERROR)

def logging(msg_success=None, msg_error=None, log_exc=True):
    def wrap(func):
        def call_with_logging(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except:
                if msg_error is not None:
                    log_error(msg_error)
                if log_exc:
                    log_exception()
            else:
                if msg_success is not None:
                    log(msg_success)
        return call_with_logging
    return wrap

def connection_error(msg):
    xbmcgui.Dialog().ok("Connection Error", msg,
                        "Please check you have a connection to the internet.")  
    
def bad_url(url, msg="URL not found."):
    xbmcgui.Dialog().ok("URL Error", msg, url,
                        "Please check the URL.")
    
def url_error(url, msg):
    log_exception()
    xbmcgui.Dialog().ok("URL Error", msg, url,
                        "Please check the log file.")
    
def write_error(path, msg):
    log_exception()
    xbmcgui.Dialog().ok("Write Error", msg, path,
                        "Check the download directory in the addon settings.")
    addon.openSettings()
    
def decompress_error(path, msg):
    log_exception()
    xbmcgui.Dialog().ok("Decompression Error",
                        "An error occurred during decompression:",
                        " ", msg)

def remove_update_files():
    update_files = glob.glob(os.path.join(constants.UPDATE_DIR, '*'))
    success = None
    log(update_files)
    for f in update_files:
        if f in constants.UPDATE_FILES or f.endswith("tar"):
            try:
                os.remove(f)
            except OSError:
                log("Could not remove " + f)
                success = False
                break
            else:
                log("Removed " + f)
                success = True
    if success or success is None:
        addon.setSetting('update_pending', 'false')
    return success

def notify(msg, time=12000):
    xbmcgui.Dialog().notification(ADDON_NAME, msg,
                                  ICON_PATH, time)
    
def busy():
    xbmc.executebuiltin("ActivateWindow(busydialog)")

def not_busy():
    xbmc.executebuiltin("Dialog.Close(busydialog)")
    
def showbusy(f):
    @functools.wraps(f)
    def busy_wrapper(*args, **kwargs):
        busy()
        try:
            return f(*args, **kwargs)
        finally:
            not_busy()
    return busy_wrapper

def build_check_prompt():
    check_prompt = int(addon.getSetting('check_prompt'))
    return check_prompt == 2 or (check_prompt == 1 and not xbmc.Player().isPlayingVideo())

def ensure_trailing_slash(path):
    return path if path.endswith('/') else path + '/'

@logging(msg_error="Unable to check if another instance is running")
def is_running():
    running = xbmcgui.Window(10000).getProperty('DevUpdateRunning') == 'True'
    log("Another instance is running" if running else "No other instance is running")
    return running

@logging("Set running flag", "Unable to set running flag")
def set_running():
    xbmcgui.Window(10000).setProperty('DevUpdateRunning', 'True')

@logging("Cleared running flag", "Unable to clear running flag")
def set_not_running():
    xbmcgui.Window(10000).clearProperty('DevUpdateRunning')

def install_cmdline_script():
    """ Creates a symbolic link to the command line download script
    in the root user home directory. The script can then be invoked
    by running:

        ./devupdate
    """

    SCRIPT_NAME = "download.py"
    script_path = os.path.join(ADDON_PATH, SCRIPT_NAME)

    SYMLINK_NAME = "devupdate"

    try:
        os.chmod(script_path, stat.S_IXUSR|stat.S_IRUSR|stat.S_IWUSR)
    except:
        log("Unable to make {} executable".format(script_path))

    symlink_path = os.path.join(os.path.expanduser('~'), SYMLINK_NAME)
    try:
        os.symlink(script_path, symlink_path)
    except:
        log("Unable to create symbolic link at {}".format(symlink_path))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == 'cancel':
            success = remove_update_files()
            if success:
                notify("Deleted update files(s)")
            elif success is not None:
                notify("Update file(s) not deleted")
