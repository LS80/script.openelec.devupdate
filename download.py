#! /usr/bin/python
############################################################################
#
#  Copyright 2012 Lee Smith
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#################################################imp###########################

import sys
import os
import time
from argparse import ArgumentParser
from urlparse import urlparse
import bz2

addons = os.path.join(os.path.expanduser('~'), '.kodi', 'addons')
if os.path.isdir(addons):
    for module in ('requests', 'beautifulsoup4'):
        path = os.path.join(addons, 'script.module.' + module, 'lib')
        sys.path.append(path)

import requests

from resources.lib.funcs import size_fmt
from resources.lib import builds
from resources.lib import constants


parser = ArgumentParser(description='Download an OpenELEC update')
parser.add_argument('-a', '--arch', help='Set the build type (e.g. Generic.x86_64, RPi.arm)')
parser.add_argument('-s', '--source', help='Set the build source')
parser.add_argument('-r', '--releases', action='store_true', help='Look for unofficial releases instead of development builds')

args = parser.parse_args()


def get_choice(items, suffix=lambda item: " "):
    print
    num_width = len(str(len(items) - 1))
    for i, item in enumerate(items):
        print "[{num:{width}d}] {item:s}\t{suffix}".format(num=i, item=item,
                                                           width=num_width, suffix=suffix(item))
    print '-' * 50

    choice = raw_input('Choose an item or "q" to quit: ')
    while choice != 'q':
        try:
            item = items[int(choice)]
            return item
        except ValueError:
            choice = raw_input('You entered a non-integer. Choice must be an'
                               ' integer or "q": ')
        except IndexError:
            choice = raw_input('You entered an invalid integer. Choice must be'
                               ' from above list or "q": ')
    sys.exit()


if args.arch:
    arch = args.arch
else:
    arch = constants.ARCH

urls = builds.sources(arch)

if args.source:
    try:
        build_url = urls[args.source]
    except KeyError:
        parsed = urlparse(args.source)
        if parsed.scheme in ('http', 'https') and parsed.netloc:
            if args.releases:
                build_url = builds.BuildsURL(args.source, extractor=builds.ReleaseLinkExtractor)
            else:
                build_url = builds.BuildsURL(args.source)
        else:
            print '"{}" is not in the list of available sources and is not a valid HTTP URL'.format(args.source)
            print 'Valid options are:\n\t{}'.format("\n\t".join(urls.keys()))
            sys.exit(1)
else:
    source = get_choice(urls.keys())
    build_url = urls[source]

installed_build = builds.get_installed_build()

def build_suffix(build):
    if build > installed_build:
        symbol = '+'
    elif build < installed_build:
        symbol = '-'
    else:
        symbol = '='
    return symbol

print
print "Arch: {}".format(arch)
print "Installed build: {}".format(installed_build)


def read(f):
    return f.read(131072)

decompressor = bz2.BZ2Decompressor()
def decompress(f):
    data = read(f)
    return decompressor.decompress(data)

def process(fin, fout, size, read_func=read):
    start_time = time.time()
    done = 0
    while done < size:
        data = read_func(fin)
        done = fin.tell()
        fout.write(data)
        percent = int(done * 100 / size)
        bytes_per_second = done / (time.time() - start_time)
        print "\r {0:3d}%   ({1}/s)   ".format(percent, size_fmt(bytes_per_second)),
        sys.stdout.flush()
    print

with build_url.extractor() as parser:
    try:
        links = sorted(parser.get_links(arch), reverse=True)
    except requests.RequestException as e:
        print str(e)
    except builds.BuildURLError as e:
        print str(e)
    else:
        if links:
            build = get_choice(links, build_suffix)
            remote = build.remote_file()
            file_path = os.path.join(constants.UPDATE_DIR, build.filename)
            print
            print "Downloading {0} ...".format(build.url)
            with open(os.path.join(constants.UPDATE_DIR, build.filename), 'w') as out:
                process(remote, out, build.size)

            if build.compressed:
                tar_path = os.path.join(constants.UPDATE_DIR, build.tar_name)
                size = os.path.getsize(file_path)
                print
                print "Decompressing {0} ...".format(file_path)
                with open(file_path, 'r') as fin, open(tar_path, 'w') as fout:
                    process(fin, fout, size, decompress)
                os.remove(file_path)

            print
            print "The update is ready to be installed. Please reboot."
        else:
            print
            print "No builds available"
