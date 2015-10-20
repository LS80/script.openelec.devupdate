from __future__ import division

import os
import bz2
import time
import hashlib

import xbmc, xbmcgui, xbmcvfs

from .script_exceptions import Canceled, WriteError, DecompressError
from .funcs import size_fmt
from .addon import L10n


class Progress(xbmcgui.DialogProgress):
    def create(self, heading, line1=None, line2=None):
        if line1 is None:
            line1 = " "
        if line2 is None:
            line2 = " "
        super(Progress, self).create(heading, line1, line2)

    def update(self, percent, message=None):
        super(Progress, self).update(percent, line3=message)


class ProgressBG(xbmcgui.DialogProgressBG):
    def iscanceled(self):
        return False

    def create(self, heading, line1=None, line2=None):
        if line1 is None:
            message = line2
        else:
            message = line1
        super(ProgressBG, self).create(heading, message)

    def update(self, percent, message=None):
        super(ProgressBG, self).update(percent)


class FileProgress(object):
    """Wraps DialogProgress(BG) as a context manager to
       handle the file progress"""

    BLOCK_SIZE = 131072

    def __init__(self, heading, infile, outpath, size, background=False):
        self._heading = heading
        self._in_f = infile
        self._outpath = outpath
        self._outfile = os.path.basename(outpath)
        self._out_f = None
        
        self._size = size
        if background:
            self._progress = ProgressBG()
        else:
            self._progress = Progress()       
        self._done = 0
 
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._in_f.close()
        if self._out_f is not None:
            self._out_f.close()

        self._progress.close()

        # If an exception occurred remove the incomplete file.
        if exc_type is not None:
            xbmcvfs.delete(self._outpath)

    def start(self):
        self._progress.create(self._heading, self._outfile, size_fmt(self._size))
        try:
            self._out_f = xbmcvfs.File(self._outpath, 'w')
        except Exception as e:
            raise WriteError(e)        
        
        start_time = time.time()
        while self._done < self._size:
            if self._progress.iscanceled():
                raise Canceled
            data = self._read()
            try:
                self._out_f.write(data)
            except Exception as e:
                raise WriteError(e)
            percent = int(self._done * 100 / self._size)
            bytes_per_second = self._done / (time.time() - start_time)
            self._progress.update(percent, "{0}/s".format(size_fmt(bytes_per_second)))

    def _getdata(self):
        return self._in_f.read(self.BLOCK_SIZE)

    def _read(self):
        data = self._getdata()
        self._done += len(data)
        return data


class DecompressProgress(FileProgress):
    decompressor = bz2.BZ2Decompressor()
    def _read(self):
        data = self._getdata()
        try:
            decompressed_data = self.decompressor.decompress(data)
        except IOError as e:
            raise DecompressError(e)
        self._done = self._in_f.tell()
        return decompressed_data
    

def reboot_countdown(title, line1, count):
    count = int(count)
    progress = xbmcgui.DialogProgress()
    progress.create(title)
        
    timed_out = True
    seconds = count
    while seconds >= 0:
        if seconds > 1:
            msg = L10n(32057).format(seconds)
        elif seconds == 1:
            msg = L10n(32058)
        else:
            msg = L10n(32059)

        progress.update(int((count - seconds) / count * 100),
                        line1, msg, " ")

        xbmc.sleep(1000)
        if progress.iscanceled():
            timed_out = False
            break
        seconds -= 1
    progress.close()
    return timed_out


def md5sum_verified(md5sum_compare, path, background):
    if background:
        verify_progress = ProgressBG()
    else:
        verify_progress = Progress()

    verify_progress.create("Verifying", line1=os.path.basename(path))

    BLOCK_SIZE = 8192

    hasher = hashlib.md5()
    f = open(path)

    done = 0
    size = os.path.getsize(path)
    while done < size:
        if verify_progress.iscanceled():
            verify_progress.close()
            return True
        data = f.read(BLOCK_SIZE)
        done += len(data)
        hasher.update(data)
        percent = int(done * 100 / size)
        verify_progress.update(percent)
    verify_progress.close()

    md5sum = hasher.hexdigest()
    return md5sum == md5sum_compare
