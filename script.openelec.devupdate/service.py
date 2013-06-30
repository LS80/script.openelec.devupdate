import os
import sys

import xbmc, xbmcgui, xbmcaddon

from lib import constants
from lib import builds

__addon__ = xbmcaddon.Addon(constants.__scriptid__)
__icon__ = __addon__.getAddonInfo('icon')


check_enabled = __addon__.getSetting('check') == 'true'
check_onbootonly = __addon__.getSetting('check_onbootonly') == 'true'
check_prompt = int(__addon__.getSetting('check_prompt'))

init = not sys.argv[0]

if init:
    if check_onbootonly:
        # Start a timer to check for a new build every hour.
        xbmc.executebuiltin("AlarmClock(openelecdevupdate,RunScript({}),01:00:00,silent,loop)".format(__file__))

    try:
        with open(constants.NOTIFY_FILE) as f:
            build = f.read()
    except IOError:
        # No new build installed
        pass
    else:
        if build == str(builds.INSTALLED_BUILD):
            xbmc.executebuiltin("Notification(OpenELEC Dev Update, Build {} was installed successfully."
                                ", 12000, {})".format(build, __icon__))
    try:
        os.remove(constants.NOTIFY_FILE)
    except:
        pass


if check_enabled:
    source = __addon__.getSetting('source')
    if isinstance(builds.INSTALLED_BUILD, builds.Release) and source == "Official Releases":
        # Don't do the job of the official auto-update system.
        pass
    else:
        try:
            subdir = __addon__.getSetting('subdir')
            if source == "Other":
                url = __addon__.getSetting('custom_url')
                build_url = builds.BuildsURL(url, subdir)
            else:
                build_url = builds.URLS[source]
                url = build_url.url
    
            with build_url.extractor() as parser:
                latest = sorted(parser.get_links(), reverse=True)[0]
                if latest > builds.INSTALLED_BUILD:
                    if (check_prompt == 1 and xbmc.Player().isPlayingVideo()) or check_prompt == 0:
                        xbmc.executebuiltin("Notification(OpenELEC Dev Update, Build {} "
                                            "is available., 7500, {})".format(latest, __icon__))
                    else:   
                        if xbmcgui.Dialog().yesno("OpenELEC Dev Update",
                                                  "A more recent build is available:   {}".format(latest),
                                                  "Show builds available to install?"):
                            xbmc.executebuiltin("RunAddon({})".format(constants.__scriptid__))         
        except:
            pass

    