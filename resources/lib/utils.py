from __future__ import division
import subprocess
import os
import sys
import glob
import functools

import xbmc, xbmcaddon, xbmcgui

import constants

addon = xbmcaddon.Addon(constants.ADDON_ID)

ADDON_NAME = addon.getAddonInfo('name')
ADDON_VERSION = xbmc.translatePath(addon.getAddonInfo('version'))
ICON_PATH = addon.getAddonInfo('icon')


def log(txt, level=xbmc.LOGNOTICE):
    if addon.getSetting('debug') == 'true':
        msg = '{} v{}: {}'.format(ADDON_NAME,
                                  ADDON_VERSION, txt)
        xbmc.log(msg, level)
        
def log_exception():
    import traceback
    log("".join(traceback.format_exception(*sys.exc_info())), xbmc.LOGERROR)
    
def connection_error(msg):
    xbmcgui.Dialog().ok("Connection Error", msg,
                        "Please check you have a connection to the internet.")  
    
def bad_url(url, msg="URL not found."):
    xbmcgui.Dialog().ok("URL Error", msg, url,
                        "Please check the URL.")
    
def url_error(url, msg):
    log_exception()
    xbmcgui.Dialog().ok("URL Error", msg, url,
                        "Please check the XBMC log file.")
    
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
        
def mount_readwrite():    
    subprocess.call(['mount', '-o', 'rw,remount', '/flash'])
    
def mount_readonly():    
    subprocess.call(['mount', '-o', 'ro,remount', '/flash'])
    
def update_extlinux():    
    subprocess.call(['/usr/bin/extlinux', '--update', '/flash'])
    
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
            
if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == 'cancel':
            success = remove_update_files()
            if success:
                notify("Deleted update files(s)")
            elif success is not None:
                notify("Update file(s) not deleted")
