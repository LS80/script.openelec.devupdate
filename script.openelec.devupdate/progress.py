import os
import bz2

import xbmcgui

from script_exceptions import Canceled, WriteError
from utils import size_fmt

class FileProgress(xbmcgui.DialogProgress):
    """Extends DialogProgress as a context manager to
       handle the file progress"""

    BLOCK_SIZE = 131072

    def __init__(self, heading, infile, outpath, size):
        xbmcgui.DialogProgress.__init__(self)
        self.create(heading, outpath, size_fmt(size))
        self._size = size
        self._in_f = infile
        try:
            self._out_f = open(outpath, 'wb')
        except IOError as e:
            raise WriteError(e)
        self._outpath = outpath
        self._done = 0
 
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._in_f.close()
        self._out_f.close()
        self.close()

        # If an exception occurred remove the incomplete file.
        if exc_type is not None:
            os.remove(self._outpath)

    def start(self):
        while self._done < self._size:
            if self.iscanceled():
                raise Canceled
            data = self._read()
            try:
                self._out_f.write(data)
            except IOError as e:
                raise WriteError(e)
            percent = int(self._done * 100 / self._size)
            self.update(percent)

    def _getdata(self):
        return self._in_f.read(self.BLOCK_SIZE)

    def _read(self):
        data = self._getdata()
        self._done += len(data)
        return data


class DecompressProgress(FileProgress):
    decompressor = bz2.BZ2Decompressor()
    def _read(self):
        data = self.decompressor.decompress(self._getdata())
        self._done = self._in_f.tell()
        return data
