import sys
import time

import xbmc, xbmcgui, xbmcaddon


from constants import __scriptid__
from builds import INSTALLED_BUILD, Release, BuildsURL, URLS

__addon__ = xbmcaddon.Addon(__scriptid__)
__icon__ = __addon__.getAddonInfo('icon')


source = __addon__.getSetting('source')

if isinstance(INSTALLED_BUILD, Release) and source == "Official Releases":
    # Don't do the job of the official auto-update system.
    sys.exit(0)

while (not xbmc.abortRequested):
    if __addon__.getSetting('check'):
        try:
            subdir = __addon__.getSetting('subdir')
            if source == "Other":
                # Custom URL
                url = __addon__.getSetting('custom_url')
                build_url = BuildsURL(url, subdir)
            else:
                # Defined URL
                build_url = URLS[source]
                url = build_url.url
    
            with build_url.extractor() as parser:
                latest = list(sorted(set(parser.get_links()), reverse=True))[0]
                if latest > INSTALLED_BUILD:
                    if xbmc.Player().isPlayingVideo():
                        xbmc.executebuiltin("Notification(OpenELEC Dev Update, Build {} "
                                            "is available., 10000, {})".format(latest, __icon__))
                    else:   
                        if xbmcgui.Dialog().yesno("OpenELEC Dev Update",
                                                  "A more recent build is available:   {}".format(latest),
                                                  "Show builds available to install?"):
                            xbmc.executebuiltin("RunAddon({})".format(__scriptid__))         
        except:
            sys.exit(0)
        
        interval = float(__addon__.getSetting('check_interval'))
        time.sleep(interval * 60)
    else:
        # Sleep for an hour before checking if the build check is now enabled.
        time.sleep(360)
  

    
    

