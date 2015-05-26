#! /usr/bin/python

# This is required to work around the ImportError exception
# "Failed to import _strptime because the import lock is held by another thread."
import _strptime

import time
import re
import os
import urlparse
from datetime import datetime
from collections import OrderedDict
from urllib2 import unquote

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
        return '{} ({})'.format(self.version,
                                self.date)

    @property
    def date(self):
        return self._datetime.strftime('%d %b %y')

    @property    
    def version(self):
        return self._version


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


class BuildLinkBase(object):

    def __init__(self, baseurl, link):
        # Set the absolute URL
        link = link.strip()
        scheme, netloc, path = urlparse.urlparse(link)[:3]
        if not scheme:
            # Construct the full url
            if not baseurl.endswith('/'):
                baseurl += '/'
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
        self.filename = unquote(os.path.basename(urlparse.urlparse(resp.url).path))

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


class BaseExtractor(object):
    URL = None

    def __init__(self, url=None):
        self.url = url if url is not None else self.URL
        self._response = None

    def _get_text(self, timeout=None):
        self._response = requests.get(self.url, timeout=timeout)
        if not self._response:
            raise BuildURLError("Build URL error: status {}".format(self._response.status_code))
        return self._response.text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._response is not None:
            self._response.close()


class BuildLinkExtractor(BaseExtractor):
    """Class to extract all the build links from the specified URL"""

    BUILD_RE = ".*OpenELEC.*-{arch}-(?:\d+\.\d+-|)[a-zA-Z]+-(\d+)-r\d+[a-z]*-g([0-9a-z]+)\.tar(|\.bz2)"
    CSS_CLASS = None

    def get_links(self, arch, timeout=None):
        self.build_re = re.compile(self.BUILD_RE.format(arch=arch))

        html = self._get_text(timeout)
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


class DropboxBuildLinkExtractor(BuildLinkExtractor):
    CSS_CLASS = 'filename-link'

        
class ReleaseLinkExtractor(BuildLinkExtractor):
    BUILD_RE = ".*OpenELEC.*-{arch}-([\d\.]+)\.tar(|\.bz2)"
    BASE_URL = None

    def _create_link(self, link):
        href = link['href']
        baseurl = self.BASE_URL if self.BASE_URL is not None else self.url
        return ReleaseLink(baseurl, href, self.build_re.match(href).group(1))


class OfficialReleaseLinkExtractor(ReleaseLinkExtractor):
    BASE_URL = "http://releases.openelec.tv"


class DualAudioReleaseLinkExtractor(ReleaseLinkExtractor):
    BUILD_RE = ".*OpenELEC-{arch}.DA-([\d\.]+)\.tar(|\.bz2)"


class MilhouseBuildLinkExtractor(BuildLinkExtractor):
    BUILD_RE = "OpenELEC-{arch}-(?:\d+\.\d+-|)Milhouse-(\d+)-(?:r|%23)(\d+[a-z]*)-g[0-9a-z]+\.tar(|\.bz2)"


class BuildInfoExtractor(BaseExtractor):
    def get_info(self, timeout):
        return {}


class MilhouseBuildInfoExtractor(BaseExtractor):
    URL = "http://forum.kodi.tv/showthread.php?tid=224025"
    R = re.compile("#(\d{4}[a-z]?).*?\((.+)\)")

    def get_info(self, timeout):
        soup = BeautifulSoup(self._get_text(timeout), 'html.parser')
        return dict(self.R.match(li.text).groups() for ul in soup.find('div', 'post-body')('ul') for li in ul('li'))

class CommitInfoExtractor(BaseExtractor):
    URL = "https://github.com/OpenELEC/OpenELEC.tv/commits/master.atom"
    R = re.compile("Commit/([0-9a-z]{7})")

    def get_info(self, timeout):
        soup = BeautifulSoup(self._get_text(timeout), 'html.parser')
        return dict((self.R.search(entry.id.text).group(1),
                     entry.title.text.strip()) for entry in soup('entry'))


class BuildsURL(object):
    def __init__(self, url, subdir=None, extractor=BuildLinkExtractor, info_extractor=BuildInfoExtractor):
        self.url = url
        if subdir:
            self.add_subdir(subdir)
        
        self._extractor = extractor
        self.info_extractor = info_extractor
        
    def __str__(self):
        return self.url
        
    def extractor(self):
        return self._extractor(self.url)
        
    def add_subdir(self, subdir):
        self._add_slash()
        self.url = urlparse.urljoin(self.url, subdir)
        self._add_slash()

    def _add_slash(self):
        if not self.url.endswith('/'):
            self.url += '/'


def get_installed_build():
    DEVEL_RE = "devel-(\d+)-r\d+-g([a-z0-9]+)"
    try:
        os_release = open('/etc/os-release').read()
    except IOError:
        pass
    else:
        if "MILHOUSE_BUILD" in os_release:
            DEVEL_RE = "devel-(\d+)-[r#](\d+)"

    try:
        version = open('/etc/version').read().rstrip()
    except IOError:
        # For testing
        version = 'devel-20141031232437-r19505-g98f5c23'

    m = re.match(DEVEL_RE, version)
    if m:
        return Build(*m.groups())
    else:
        # A full release is installed.
        return Release(version)


def sources(arch):
    sources_dict = OrderedDict()
    sources_dict["Official Snapshot Builds"] = BuildsURL("http://snapshots.openelec.tv",
                                                         info_extractor=CommitInfoExtractor)

    if arch.startswith("RPi"):
        sources_dict["Milhouse RPi Builds"] = BuildsURL("http://milhouse.openelec.tv/builds/master",
                                                        subdir=arch.split('.')[0],
                                                        extractor=MilhouseBuildLinkExtractor,
                                                        info_extractor=MilhouseBuildInfoExtractor)
        sources_dict["Chris Swan RPi Builds"] = BuildsURL("http://resources.pichimney.com/OpenELEC/dev_builds",
                                                          info_extractor=CommitInfoExtractor)

    sources_dict["Official Releases"] = BuildsURL("http://openelec.mirrors.uk2.net",
                                                  extractor=OfficialReleaseLinkExtractor)
    sources_dict["Official Archive"] = BuildsURL("http://archive.openelec.tv", extractor=ReleaseLinkExtractor)

    sources_dict["DarkAngel2401 Dual Audio Builds"] = BuildsURL("http://openelec-dualaudio.subcarrier.de/OpenELEC-DualAudio/",
                                                                subdir=arch,
                                                                extractor=DualAudioReleaseLinkExtractor)
    return sources_dict


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
