from __future__ import division
import subprocess
import os
import sys
import glob

import xbmc, xbmcaddon, xbmcgui

import constants

__addon__ = xbmcaddon.Addon(constants.__scriptid__)
__icon__ = __addon__.getAddonInfo('icon')

def log(txt, level=xbmc.LOGNOTICE):
    if __addon__.getSetting('debug') == 'true':
        msg = '{} v{}: {}'.format(__addon__.getAddonInfo('name'),
                                  __addon__.getAddonInfo('version'), txt)
        xbmc.log(msg, level)
        
def log_exception():
    import traceback
    log("".join(traceback.format_exception(*sys.exc_info())), xbmc.LOGERROR)
    
def connection_error(msg):
    xbmcgui.Dialog().ok("Connection Error", msg,
                        "Please check you have a connection to the internet.")  
    
def bad_url(url, msg="URL not found."):
    xbmcgui.Dialog().ok("URL Error", msg, url,
                        "Please check the URL in the addon settings.")
    __addon__.openSettings()

def bad_source(source, msg="Source not found."):
    xbmcgui.Dialog().ok("URL Error", msg, source,
                        "Please set the source.")
    __addon__.openSettings()
    
def url_error(url, msg):
    log_exception()
    xbmcgui.Dialog().ok("URL Error", msg, url,
                        "Please check the XBMC log file.")
    
def write_error(path, msg):
    log_exception()
    xbmcgui.Dialog().ok("Write Error", msg, path,
                        "Check the download directory in the addon settings.")
    __addon__.openSettings()
    
def decompress_error(path, msg):
    log_exception()
    xbmcgui.Dialog().ok("Decompression Error",
                        "An error occurred during decompression:",
                        " ", msg)

def size_fmt(num):
    for s, f in (('bytes', '{0:.0f}'), ('KB', '{0:.1f}'), ('MB', '{0:.1f}')):
        if num < 1024.0:
            return (f + " {1}").format(num, s)
        num /= 1024.0
        
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
        __addon__.setSetting('update_pending', 'false')
    return success

def notify(msg, time=12000):
    xbmcgui.Dialog().notification("OpenELEC Dev Update", msg, __icon__, time)
            
if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == 'cancel':
            success = remove_update_files()
            if success:
                notify("Deleted update files(s)")
            elif success is not None:
                notify("Update file(s) not deleted")
