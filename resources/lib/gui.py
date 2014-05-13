import xbmc
import xbmcgui
import xbmcaddon

import constants

__addon__ = xbmcaddon.Addon(constants.__scriptid__)
__path__ = xbmc.translatePath(__addon__.getAddonInfo('path'))


class BuildSelect(xbmcgui.WindowXMLDialog):
    LIST_ID = 500
    LABEL_ID = 400
    
    def __new__(cls, arch):
        return super(BuildSelect, cls).__new__(cls, "Dialog.xml", __path__)
    
    def __init__(self, arch):
        self._arch = arch

    def __nonzero__(self):
        return self._selected is not None

    def setBuilds(self, builds):
        self._builds = builds
        
    def setSource(self, source):
        self._source = source

    def onInit(self):
        self._selected = None

        self._list = self.getControl(self.LIST_ID)
        self._list.addItems(self._builds)
        
        label = "{0}[CR][CR]{1}[CR][CR] * = currently installed build".format(self._arch,
                                                                              self._source)
        self.getControl(self.LABEL_ID).setLabel(label)
        
        self.setFocusId(self.LIST_ID)

    @property
    def selected(self):
        return self._selected

    def onClick(self, controlID):
        self._selected = self._list.getSelectedPosition()
        self.close()

