#! /usr/bin/python

import time
import re
import os
import urlparse
from datetime import datetime
from collections import OrderedDict

from bs4 import BeautifulSoup, SoupStrainer
import requests

import constants


class BuildURLError(Exception):
    pass

class Build(object):
    """Holds information about an OpenELEC build,
       including how to sort and print them."""
       
    DATETIME_FMT = '%Y%m%d%H%M%S'

    def __init__(self, _datetime, version):
        self._version = version
        if isinstance(_datetime, datetime):
            self._datetime = _datetime
        else:
            try:
                self._datetime = datetime.strptime(_datetime, self.DATETIME_FMT)
            except TypeError:
                # Work around an issue with datetime.strptime when the script is run a second time.
                #raise
                self._datetime = datetime(*(time.strptime(_datetime, self.DATETIME_FMT)[0:6]))

    def __eq__(self, other):
        return (self._version, self._datetime) == (other._version, other._datetime)

    def __hash__(self):
        return hash((self._version, self._datetime))

    def __lt__(self, other):
        return self._datetime < other._datetime
    
    def __gt__(self, other):
        return self._datetime > other._datetime

    def __str__(self):
        return '{} ({})'.format(self._version,
                                self._datetime.strftime('%d %b %y'))


class Release(Build):
    DATETIME_FMT = '%Y-%m-%dT%H:%M:%S'
    tag_soup = None

    def __init__(self, version):        
        self.maybe_get_tags()
        tag = self.tag_soup.find('span', text=version)
        if tag is not None:
            self._has_date = True
            Build.__init__(self, tag.previous_sibling['datetime'][:19], version)
        else:
            self._has_date = False
        self.release = [int(p) for p in version.split('.')]
        
    def is_valid(self):
        return self._has_date and self.release >= [3,95,0]
    
    __nonzero__ = is_valid

    @classmethod
    def tag_match(cls, tag, attrs):
        return (tag == 'time' or
               ('class' in attrs and attrs['class'] == 'tag-name'))
        
    @classmethod
    def maybe_get_tags(cls):
        if cls.tag_soup is None:
            html = requests.get("http://github.com/OpenELEC/OpenELEC.tv/releases").text
            cls.tag_soup = BeautifulSoup(html, 'html.parser',
                                         parse_only=SoupStrainer(cls.tag_match))


class RbejBuild(Build):
    DATETIME_FMT = '%d.%m.%Y'


class BuildLinkBase(object):

    def __init__(self, baseurl, link):
        # Set the absolute URL
        link = link.strip()
        scheme, netloc, path = urlparse.urlparse(link)[:3]
        if not scheme:
            # Construct the full url
            self.url = urlparse.urljoin(baseurl, link)
        else:
            if netloc == "www.dropbox.com":
                # Fix Dropbox url
                link = urlparse.urlunparse((scheme, "dl.dropbox.com", path, None, None, None))
            self.url = link

    def remote_file(self):
        resp = requests.get(self.url, stream=True,
                            headers={'Accept-Encoding': None})
        try:
            self.size = int(resp.headers['Content-Length'])
        except KeyError:
            self.size = 0

        # Get the actual filename
        self.filename = os.path.basename(urlparse.urlparse(resp.url).path)

        name, ext = os.path.splitext(self.filename)
        if ext == '.tar':
            self.tar_name = self.filename
        else:
            self.tar_name = name
            
        if ext == '.bz2':
            self.compressed = True
        else:
            self.compressed = False
            
        return resp.raw


class BuildLink(Build, BuildLinkBase):
    """Holds information about a link to an OpenELEC build."""

    def __init__(self, baseurl, link, datetime_str, revision):
        BuildLinkBase.__init__(self, baseurl, link)
        Build.__init__(self, datetime_str, version=revision)


class ReleaseLink(Release, BuildLinkBase):
    """Class for links to official release downloads."""
    
    def __init__(self, baseurl, link, release):
        BuildLinkBase.__init__(self, baseurl, link)
        Release.__init__(self, release)


class RbejBuildLink(RbejBuild, BuildLinkBase):
    def __init__(self, baseurl, link, version, datetime_str):
        BuildLinkBase.__init__(baseurl, link)
        RbejBuild.__init__(self, datetime_str, version)


class BuildLinkExtractor(object):
    """Class to extract all the build links from the specified URL"""

    BUILD_RE = ".*OpenELEC.*-{0}-[a-zA-Z]+-(\d+)-r(\d+)(|-g[0-9a-z]+)\.tar(|\.bz2)"
    CSS_CLASS = None

    def __init__(self, url):
        self.url = url
        self._response = None

    def get_links(self, arch, timeout=None):
        self.build_re = re.compile(self.BUILD_RE.format(arch))

        self._response = requests.get(self.url, timeout=timeout)
        if not self._response:
            raise BuildURLError("Build URL error: status {}".format(self._response.status_code))

        html = self._response.text
        args = ['a']
        if self.CSS_CLASS is not None:
            args.append(self.CSS_CLASS)
            
        soup = BeautifulSoup(html, 'html.parser',
                             parse_only=SoupStrainer(*args, href=self.build_re))
                        
        self._links = soup.contents

        for link in self._links:
            l = self._create_link(link)
            if l:
                yield l

    def _create_link(self, link):
        href = link['href']
        return BuildLink(self.url, href, *self.build_re.match(href).groups()[:2])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._response is not None:
            self._response.close()


class DropboxBuildLinkExtractor(BuildLinkExtractor):

    CSS_CLASS = 'filename-link'
        
        
class ReleaseLinkExtractor(BuildLinkExtractor):

    BUILD_RE = ".*OpenELEC.*-{0}-([\d\.]+)\.tar(|\.bz2)"

    def _create_link(self, link):
        href = link['href']
        return ReleaseLink(self.url, href, self.build_re.match(href).group(1))


class RbejBuildLinkExtractor(BuildLinkExtractor):

    BUILD_RE = ".*OpenELEC.*-{0}-(.*?)\((.*?)\)\.tar(|\.bz2)"

    def _create_link(self, link):
        href = link['href']
        m = self.build_re.match(href)
        datetime_str = m.group(2)
        desc = m.group(1).split('-')
        version = "{} {}".format(desc[0], desc[2])
        return RbejBuildLink(self.url, href.strip(), version, datetime_str)


class DualAudioReleaseLinkExtractor(ReleaseLinkExtractor):

    BUILD_RE = ".*OpenELEC-{0}.DA-([\d\.]+)\.tar(|\.bz2)"


class BuildsURL(object):
    def __init__(self, url, subdir=None, extractor=BuildLinkExtractor):
        self.url = url
        if subdir:
            self.add_subdir(subdir)
        
        self._extractor = extractor
        
    def extractor(self):
        return self._extractor(self.url)
        
    def add_subdir(self, subdir):
        self.url = urlparse.urljoin(self.url, subdir)
        self._add_slash()

    def _add_slash(self):
        if not self.url.endswith('/'):
            self.url += '/'


def get_installed_build():
# Create an INSTALLED_BUILD object for comparison
    try:
        version = open('/etc/version').read().rstrip()
    except IOError:
        version = 'devel-20140403222729-r18089-gb97d61d'
    
    m = re.search("devel-(\d+)-r(\d+)", version)
    if m:
        if constants.ARCH == 'RPi.arm':
            try:
                f = open('/usr/lib/xbmc/xbmc.bin')
            except IOError:
                f = open('/usr/lib/kodi/kodi.bin')
            mm = re.search('Rbej (Frodo|Gotham)', f.read())
            if mm:
                version = "Rbej {}".format(mm.group(1))
                # Rbej builds do not have a time as part of the name
                datetime_str = m.group(1)[:8] + '0'*6
                return Build(datetime_str, version)
            else:
                return Build(*m.groups())
        else:
            return Build(*m.groups())
    else:
        # A full release is installed.
        return Release(version)


def sources(arch):
    return OrderedDict((
                       ("Official Snapshot Builds",
                        BuildsURL("http://snapshots.openelec.tv")),
                       ("Official Releases",
                        BuildsURL("http://releases.openelec.tv",
                                  extractor=ReleaseLinkExtractor)),
                       ("Official Archive",
                        BuildsURL("http://archive.openelec.tv", extractor=ReleaseLinkExtractor)),
                       ("XBMCNightlyBuilds (Nightly Builds)",
                        BuildsURL("http://mirrors.xbmcnightlybuilds.com/OpenELEC_DEV_BUILDS",
                                  subdir=arch.split('.')[0])),
                       ("XBMCNightlyBuilds (Official Stable Builds Mirror)",
                        BuildsURL("http://mirrors.xbmcnightlybuilds.com/OpenELEC_STABLE_BUILDS",
                                  extractor=ReleaseLinkExtractor)),
                       ("Chris Swan (RPi)",
                        BuildsURL("http://resources.pichimney.com/OpenELEC/dev_builds")),
                       ("Rbej Gotham Builds (RPi)",
                        BuildsURL("http://netlir.dk/rbej/builds/Gotham",
                                  extractor=RbejBuildLinkExtractor)),
                       ("MilhouseVH Builds (RPi)",
                        BuildsURL("http://netlir.dk/rbej/builds/MilhouseVH")),
                       ("DarkAngel2401 Dual Audio Builds",
                        BuildsURL("http://openelec-dualaudio.subcarrier.de/OpenELEC-DualAudio/", subdir=arch,
                                  extractor=DualAudioReleaseLinkExtractor))
                      ))


if __name__ == "__main__":
    import sys
    
    installed_build = get_installed_build()

    def print_links(name, build_url, arch):
        print name
        try:
            with build_url.extractor() as parser:
                for link in sorted(set(parser.get_links(arch)), reverse=True):
                    print "\t{:25s}".format(str(link) + ' *' * (link > installed_build))
        except requests.RequestException as e:
            print str(e)
        except BuildURLError as e:
            print str(e)
        print

    print "Installed build = {}".format(installed_build)
    print

    urls = sources(constants.ARCH)

    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in urls:
            print '"{}" not in URL list'.format(name)
        else:
            print_links(name, urls[name], constants.ARCH)
    else:
        for name, build_url in urls.items():
            print_links(name, build_url, constants.ARCH)
