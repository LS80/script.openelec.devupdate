import sys

import xbmc, xbmcgui, xbmcaddon


from constants import __scriptid__
from builds import INSTALLED_BUILD, Release, BuildsURL, URLS

__addon__ = xbmcaddon.Addon(__scriptid__)
__icon__ = __addon__.getAddonInfo('icon')


if not sys.argv[0]:
    xbmc.executebuiltin("AlarmClock(OpenELECDevUpdate,XBMC.RunScript({}),00:30:00,silent,loop)".format(__file__))
    if __addon__.getSetting('check') == 'true':
        xbmc.executebuiltin("AlarmClock(OpenELECDevUpdateFirst,XBMC.RunScript({},started),00:00:30,silent)".format(__file__))
        interval = int(__addon__.getSetting('check_interval'))
        xbmc.executebuiltin("AlarmClock(OpenELECDevUpdateCheck,XBMC.RunScript({},started),00:{}:00,silent,loop)".format(__file__, interval))
    else:
        xbmc.executebuiltin("CancelAlarm(OpenELECDevUpdateCheck,silent)")
elif sys.argv[0] and sys.argv[1] == 'started':
    source = __addon__.getSetting('source')
    if isinstance(INSTALLED_BUILD, Release) and source == "Official Releases":
        # Don't do the job of the official auto-update system.
        pass
    else:
        try:
            subdir = __addon__.getSetting('subdir')
            if source == "Other":
                url = __addon__.getSetting('custom_url')
                build_url = BuildsURL(url, subdir)
            else:
                build_url = URLS[source]
                url = build_url.url
    
            with build_url.extractor() as parser:
                latest = list(sorted(set(parser.get_links()), reverse=True))[0]
                if latest > INSTALLED_BUILD:
                    if xbmc.Player().isPlayingVideo():
                        xbmc.executebuiltin("Notification(OpenELEC Dev Update, Build {} "
                                            "is available., 7500, {})".format(latest, __icon__))
                    else:   
                        if xbmcgui.Dialog().yesno("OpenELEC Dev Update",
                                                  "A more recent build is available:   {}".format(latest),
                                                  "Show builds available to install?"):
                            xbmc.executebuiltin("RunAddon({})".format(__scriptid__))         
        except:
            pass

