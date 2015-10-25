import xbmc, xbmcaddon

__addon = xbmcaddon.Addon('script.openelec.devupdate')

info = __addon.getAddonInfo
get_setting = __addon.getSetting
set_setting = __addon.setSetting
open_settings = __addon.openSettings
L10n = __addon.getLocalizedString

def get_bool_setting(setting):
    return get_setting(setting) == 'true'

def get_int_setting(setting):
    return int(get_setting(setting))

name = info('name')
version = info('version')
data_path = xbmc.translatePath(info('profile'))
src_path = xbmc.translatePath(info('path'))
icon_path = info('icon')
