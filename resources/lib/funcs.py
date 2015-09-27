import os
import sys

def size_fmt(num):
    for s, f in (('bytes', '{0:.0f}'), ('KB', '{0:.1f}'), ('MB', '{0:.1f}')):
        if num < 1024.0:
            return (f + " {1}").format(num, s)
        num /= 1024.0

def add_deps_to_path():
    addons = os.path.join(os.path.expanduser('~'), '.kodi', 'addons')
    if os.path.isdir(addons):
        for module in ('requests', 'beautifulsoup4', 'html2text'):
            path = os.path.join(addons, 'script.module.' + module, 'lib')
            sys.path.append(path)
