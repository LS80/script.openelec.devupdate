import threading

import xbmcgui
import requests

from . import addon, builds, utils, log, history, funcs
from .addon import L10n


class BaseInfoDialog(xbmcgui.WindowXMLDialog):
    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_SHOW_INFO,
                         xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()


class InfoDialog(BaseInfoDialog):
    def __new__(cls, *args):
        return super(InfoDialog, cls).__new__(
            cls, "script-devupdate-info.xml", addon.src_path)

    def __init__(self, title, text):
        self._title = title
        self._text = text

    def onInit(self):
        self.getControl(1).setLabel(self._title)
        self.getControl(2).setText(self._text)


class HistoryDialog(BaseInfoDialog):
    def __new__(cls, *args):
        return super(HistoryDialog, cls).__new__(
            cls, "script-devupdate-history.xml", addon.src_path)

    def __init__(self, history):
        self._history = history

    def onInit(self):
        if self._history is not None:
            self.getControl(1).setLabel(L10n(32031))
            install_list = self.getControl(2)
            for install in reversed(self._history):
                li = xbmcgui.ListItem()
                for attr in ('source', 'version'):
                    li.setProperty(attr, str(getattr(install, attr)))
                li.setProperty('timestamp', install.timestamp.strftime("%Y-%m-%d %H:%M"))
                install_list.addItem(li)
        else:
            self.getControl(1).setLabel(L10n(32032))


class BuildSelectDialog(xbmcgui.WindowXMLDialog):
    LABEL_ID = 100
    BUILD_LIST_ID = 20
    SOURCE_LIST_ID = 10
    INFO_TEXTBOX_ID = 200
    SETTINGS_BUTTON_ID = 30
    HISTORY_BUTTON_ID = 40
    CANCEL_BUTTON_ID = 50

    def __new__(cls, *args):
        return super(BuildSelectDialog, cls).__new__(
            cls, "script-devupdate-main.xml", addon.src_path)

    def __init__(self, installed_build):
        self._installed_build = installed_build

        self._sources = builds.sources()
        utils.add_custom_sources(self._sources)

        self._initial_source = addon.get_setting('source_name')
        try:
            self._build_url = self._sources[self._initial_source]
        except KeyError:
            self._build_url = self._sources.itervalues().next()
            self._initial_source = self._sources.iterkeys().next()
        self._builds = self._get_build_links(self._build_url)

        self._build_infos = {}

    def __nonzero__(self):
        return self._selected_build is not None

    def onInit(self):
        self._selected_build = None

        self._sources_list = self.getControl(self.SOURCE_LIST_ID)
        self._sources_list.addItems(self._sources.keys())

        self._build_list = self.getControl(self.BUILD_LIST_ID)

        self.getControl(self.LABEL_ID).setLabel(builds.arch)

        self._info_textbox = self.getControl(self.INFO_TEXTBOX_ID)

        if self._builds:
            self._selected_source_position = self._sources.keys().index(self._initial_source)

            self._set_builds(self._builds)
        else:
            self._selected_source_position = 0
            self._initial_source = self._sources.iterkeys().next()
            self.setFocusId(self.SOURCE_LIST_ID)

        self._selected_source = self._initial_source

        self._sources_list.selectItem(self._selected_source_position)

        item = self._sources_list.getListItem(self._selected_source_position)
        self._selected_source_item = item
        self._selected_source_item.setLabel2('selected')

        self._cancel_button = self.getControl(self.CANCEL_BUTTON_ID)
        self._cancel_button.setVisible(bool(funcs.update_files()))

        threading.Thread(target=self._get_and_set_build_info,
                         args=(self._build_url,)).start()

    @property
    def selected_build(self):
        return self._selected_build

    @property
    def selected_source(self):
        return self._selected_source

    def onClick(self, controlID):
        if controlID == self.BUILD_LIST_ID:
            self._selected_build = self._builds[self._build_list.getSelectedPosition()]
            self.close()
        elif controlID == self.SOURCE_LIST_ID:
            self._build_url = self._get_build_url()
            build_links = self._get_build_links(self._build_url)

            if build_links:
                self._selected_source_item.setLabel2('')
                self._selected_source_item = self._sources_list.getSelectedItem()
                self._selected_source_position = self._sources_list.getSelectedPosition()
                self._selected_source_item.setLabel2('selected')
                self._selected_source = self._selected_source_item.getLabel()

                self._set_builds(build_links)

                threading.Thread(target=self._get_and_set_build_info,
                                 args=(self._build_url,)).start()
            else:
                self._sources_list.selectItem(self._selected_source_position)
        elif controlID == self.SETTINGS_BUTTON_ID:
            self.close()
            addon.open_settings()
        elif controlID == self.HISTORY_BUTTON_ID:
            dialog = HistoryDialog(history.get_full_install_history())
            dialog.doModal()
        elif controlID == self.CANCEL_BUTTON_ID:
            if utils.remove_update_files():
                utils.notify(L10n(32034))
                self._cancel_button.setVisible(False)
                funcs.remove_notify_file()
                self._info_textbox.setText("")

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_MOVE_DOWN, xbmcgui.ACTION_MOVE_UP,
                         xbmcgui.ACTION_PAGE_DOWN, xbmcgui.ACTION_PAGE_UP,
                         xbmcgui.ACTION_MOUSE_MOVE):
            self._set_build_info()

        elif action_id == xbmcgui.ACTION_SHOW_INFO:
            build_version = self._build_list.getSelectedItem().getLabel()
            try:
                info = self._build_infos[build_version]
            except KeyError:
                log.log("Build details for build {} not found".format(build_version))
            else:
                if info.details is not None:
                    try:
                        details = info.details.get_text()
                    except Exception as e:
                        log.log("Unable to retrieve build details: {}".format(e))
                    else:
                        if details:
                            build = "[B]{}[/B]\n\n".format(L10n(32035)).format(build_version)
                            dialog = InfoDialog(build, details)
                            dialog.doModal()

        elif action_id in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()

    def onFocus(self, controlID):
        if controlID != self.BUILD_LIST_ID:
            self._info_textbox.setText("")
            self._builds_focused = False

        if controlID == self.BUILD_LIST_ID:
            self._builds_focused = True
            self._set_build_info()
        elif controlID == self.SOURCE_LIST_ID:
            self._info_textbox.setText("[COLOR=white]{}[/COLOR]".format(L10n(32141)))
        elif controlID == self.SETTINGS_BUTTON_ID:
            self._info_textbox.setText("[COLOR=white]{}[/COLOR]".format(L10n(32036)))
        elif controlID == self.HISTORY_BUTTON_ID:
            self._info_textbox.setText("[COLOR=white]{}[/COLOR]".format(L10n(32037)))
        elif controlID == self.CANCEL_BUTTON_ID:
            self._info_textbox.setText("[COLOR=white]{}[/COLOR]".format(L10n(32038)))

    @utils.showbusy
    def _get_build_links(self, build_url):
        links = []
        try:
            links = build_url.builds()
        except requests.ConnectionError as e:
            utils.connection_error(str(e))
        except builds.BuildURLError as e:
            utils.bad_url(build_url.url, str(e))
        except requests.RequestException as e:
            utils.url_error(build_url.url, str(e))
        else:
            if not links:
                utils.bad_url(build_url.url, L10n(32039).format(builds.arch))
        return links

    def _get_build_infos(self, build_url):
        log.log("Retrieving build information")
        info = {}
        for info_extractor in build_url.info_extractors:
            try:
                info.update(info_extractor.get_info())
            except Exception as e:
                log.log("Unable to retrieve build info: {}".format(str(e)))
        return info

    def _set_build_info(self):
        if self._builds_focused:
            selected_item = self._build_list.getSelectedItem()
            try:
                build_version = selected_item.getLabel()
            except AttributeError:
                log.log("Unable to get selected build name")
            else:
                try:
                    info = self._build_infos[build_version].summary
                except KeyError:
                    info = ""
                    log.log("Build info for build {} not found".format(build_version))
                else:
                    log.log("Info for build {}:\n\t{}".format(build_version, info))
            self._info_textbox.setText(info)

    def _get_and_set_build_info(self, build_url):
        self._build_infos = self._get_build_infos(build_url)
        self._set_build_info()

    def _get_build_url(self):
        source = self._sources_list.getSelectedItem().getLabel()
        build_url = self._sources[source]

        log.log("Full URL = " + build_url.url)
        return build_url

    def _set_builds(self, builds):
        self._builds = builds
        self._build_list.reset()
        for build in builds:
            li = xbmcgui.ListItem()
            li.setLabel(build.version)
            li.setLabel2(build.date)
            if build > self._installed_build:
                icon = 'upgrade'
            elif build < self._installed_build:
                icon = 'downgrade'
            else:
                icon = 'installed'
            li.setIconImage("{}.png".format(icon))
            self._build_list.addItem(li)
        self.setFocusId(self.BUILD_LIST_ID)
        self._builds_focused = True
