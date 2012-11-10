from __future__ import division

def size_fmt(num):
    for s, f in (('bytes', '{0:d}'), ('KB', '{0:.1f)'), ('MB', '{0:.1f}')):
        if num < 1024.0:
            return (f + " {1}").format(num, s)
        num /= 1024.0