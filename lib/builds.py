import time
import re
import os
import urlparse
import urllib2
import socket
from datetime import datetime
from collections import OrderedDict
import gzip
from StringIO import StringIO

from BeautifulSoup import BeautifulSoup, SoupStrainer

from constants import ARCH, HEADERS, __scriptid__

try:
    import xbmcaddon
except:
    pass
else:
    if xbmcaddon.Addon(__scriptid__).getSetting('set_arch') == 'true':
        ARCH = xbmcaddon.Addon(__scriptid__).getSetting('arch')


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
    DATETIME_FMT = '%Y-%m-%d %H:%M:%S'
    tag_soup = None
    latest = None

    def __init__(self, version):        
        self.maybe_get_tags()
        tag = self.tag_soup.find('a', href=re.compile(version))
        if tag is not None:
            self._has_date = True
            Build.__init__(self, tag.time['title'], version)
        else:
            self._has_date = False
        
    def is_valid(self):
        return self._has_date
    
    __nonzero__ = is_valid
        
    @classmethod
    def maybe_get_tags(cls):
        if cls.tag_soup is None:
            req = urllib2.Request("http://github.com/OpenELEC/OpenELEC.tv/tags", None, HEADERS)
            html = urllib2.urlopen(req).read()
            cls.tag_soup = BeautifulSoup(html,
                                         SoupStrainer('a', href=re.compile("/OpenELEC/OpenELEC.tv/releases")))
      

class RbejBuild(Build):
    DATETIME_FMT = '%d.%m.%Y'


class BuildLinkBase(object):

    def _set_info(self):

        name, ext = os.path.splitext(self.filename)
        if ext == '.tar':
            self.tar_name = self.filename
        else:
            self.tar_name = name
            
        if ext == '.bz2':
            self.compressed = True
        else:
            self.compressed = False

        self.archive = None

    def set_archive(self, path):
        self.archive = os.path.join(path, self.tar_name)


class BuildLink(Build, BuildLinkBase):
    """Holds information about a link to an OpenELEC build."""

    def __init__(self, baseurl, link, revision, datetime_str):
        Build.__init__(self, datetime_str, version=revision)

        scheme, netloc, path = urlparse.urlparse(link)[:3]
        if not scheme:
            # Construct the full url
            self.url = urlparse.urljoin(baseurl, link)
        else:
            if netloc == "www.dropbox.com":
                # Fix Dropbox url
                link = urlparse.urlunparse((scheme, "dl.dropbox.com", path, None, None, None))
            self.url = link

        # Extract the file name part
        self.filename = os.path.basename(link)

        self._set_info()


class ArchiveLink(Release, BuildLinkBase):
    ''' Class for links to official archive release downloads '''
    
    def __init__(self, version, baseurl, filename):
        self.filename = filename
        self.url = urlparse.urljoin(baseurl, filename)
        self._set_info()
        
        Release.__init__(self, version)


class ReleaseLink(Release, BuildLinkBase):
    ''' Class for links to official release downloads '''

    BASEURL = "http://releases.openelec.tv"
    
    def __init__(self, version):
        filename = "OpenELEC-{}-{}.tar.bz2".format(ARCH, version)
        # Check if the link exists with or without the .bz2 extension.
        for f in (os.path.splitext(filename)[0], filename):
            url = urlparse.urljoin(self.BASEURL, f)
            req = urllib2.Request(url, None, HEADERS)
            try:
                urllib2.urlopen(req)
            except (urllib2.HTTPError, socket.error):
                self._exists = False
            else:
                self._exists = True
                self.filename = f
                self.url = url
                self._set_info()
                break
        
        Release.__init__(self, version)
        
    def __nonzero__(self):
        return self.is_valid() and self._exists


class RbejBuildLink(RbejBuild, BuildLinkBase):
    def __init__(self, baseurl, link, version, datetime_str):
        RbejBuild.__init__(self, datetime_str, version)
        self.filename = os.path.basename(link)
        self.url = urlparse.urljoin(baseurl, link)
        
        self._set_info()


class BuildLinkExtractor(object):
    """Class to extract all the build links from the specified URL"""

    BUILD_RE = re.compile(".*OpenELEC.*-{0}-[a-zA-Z]+-(\d+)-r(\d+)(|-g[0-9a-z]+).tar(|.bz2)$".format(ARCH))
    TAG = 'a'
    CLASS = None
    HREF = BUILD_RE
    TEXT = None

    def __init__(self, url):
        self._url = url

        request = urllib2.Request(url, None, HEADERS)
        request.add_header('Accept-encoding', "gzip")

        self._response = urllib2.urlopen(request)

        if self._response.info().get('Content-Encoding') == "gzip":
            f = gzip.GzipFile(fileobj=StringIO(self._response.read()))
        else:
            f = self._response

        html = f.read()
        soup = BeautifulSoup(html, parseOnlyThese=SoupStrainer(self.TAG,
                                                               self.CLASS,
                                                               href=self.HREF,
                                                               text=self.TEXT))
        self._links = soup.contents

    def get_links(self):
        for link in self._links:
            l = self._create_link(link)
            if l:
                yield l

    def _create_link(self, link):
        href = link['href']
        datetime_str, revision = self.BUILD_RE.match(href).groups()[:2]
        return BuildLink(self._url, href.strip(), revision, datetime_str)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._response.close()


class DropboxLinkExtractor(BuildLinkExtractor):

    CLASS = 'filename-link'
        
        
class ReleaseLinkExtractor(BuildLinkExtractor):
    
    BUILD_RE = re.compile(".*OpenELEC.*i386 Version:([\d\.]+)")
    TAG = 'tr'
    TEXT = BUILD_RE
    HREF = None
    
    #DATE_RE = re.compile("(\d{4}-\d{2}-\d{2})")

    def get_links(self):
        for link in self._links:
            version = self.BUILD_RE.match(link).group(1)
            #build_date = link.findNext(text=self.DATE_RE).strip()
            
            # Look for older releases.
            version_parts = [int(i) for i in version.split('.')]
            all_versions = []
            start_minor = version_parts[-1]
            for i in range(int(version_parts[1]), -1, -1):
                for j in range(start_minor, -1, -1):
                    all_versions.append('{}.{}.{}'.format(version_parts[0],i,j))
                start_minor = 9
            for v in all_versions:
                rl = ReleaseLink(v)
                if rl:
                    yield rl


class ArchiveLinkExtractor(BuildLinkExtractor):

    BUILD_RE = re.compile(".*OpenELEC.*-{0}-([\d\.]+).tar(|.bz2)".format(ARCH), re.DOTALL)
    TEXT = BUILD_RE

    def _create_link(self, link):
        version = self.BUILD_RE.match(link).group(1)
        return ArchiveLink(version, self._url, link.strip())


class RbejLinkExtractor(BuildLinkExtractor):

    BUILD_RE = re.compile(".*OpenELEC.*-{0}-(.*?)\((.*?)\).tar(|.bz2)".format(ARCH))
    HREF = BUILD_RE

    def _create_link(self, link):
        href = link['href']
        m = self.BUILD_RE.match(href)
        datetime_str = m.group(2)
        desc = m.group(1).split('-')
        version = "{} {}".format(desc[0], desc[2])
        return RbejBuildLink(self._url, href.strip(), version, datetime_str)    




class BuildsURL(object):
    def __init__(self, url, subdir=None, extractor=BuildLinkExtractor):
        self.url = url
        self._add_slash()
        if subdir:
            self._add_subdir(subdir)
        
        self._extractor = extractor
        
    def extractor(self):
        return self._extractor(self.url)
        
    def _add_subdir(self, subdir):
        self.url = urlparse.urljoin(self.url, subdir)
        self._add_slash()

    def _add_slash(self):
        if not self.url.endswith('/'):
            self.url += '/'


# Create an INSTALLED_BUILD object for comparison
try:
    VERSION = open('/etc/version').read().rstrip()
except IOError:
    VERSION = '3.2.0'

m = re.search("devel-(\d+)-r(\d+)", VERSION)
if m:
    if ARCH == 'RPi.arm':
        mm = re.search('Rbej (Frodo|Gotham)', open('/usr/lib/xbmc/xbmc.bin').read())
        if mm:
            version = "Rbej {}".format(mm.group(1))
            # Rbej builds do not have a time as part of the name
            datetime_str = m.group(1)[:8] + '0'*6
            INSTALLED_BUILD = Build(datetime_str, version)
        else:
            INSTALLED_BUILD = Build(*m.groups())
    else:
        INSTALLED_BUILD = Build(*m.groups())
else:
    # A full release is installed.
    INSTALLED_BUILD = Release(VERSION)
    
    
URLS = OrderedDict((
                   ("Official Daily Builds",
                    BuildsURL("http://sources.openelec.tv/tmp/image")),
                   ("Official Releases",
                    BuildsURL("http://openelec.tv/get-openelec/viewcategory/8-generic-builds",
                              extractor=ReleaseLinkExtractor)),
                   ("Official Archive",
                    BuildsURL("http://archive.openelec.tv", extractor=ArchiveLinkExtractor)),
                   ("XBMCNightlyBuilds (Nightly Builds)",
                    BuildsURL("http://mirrors.xbmcnightlybuilds.com/OpenELEC_DEV_BUILDS",
                              subdir=ARCH.split('.')[0])),
                   ("XBMCNightlyBuilds (Official Stable Builds Mirror)",
                    BuildsURL("http://mirrors.xbmcnightlybuilds.com/OpenELEC_STABLE_BUILDS",
                              extractor=ArchiveLinkExtractor)),
                   ("Chris Swan (RPi)",
                    BuildsURL("http://resources.pichimney.com/OpenELEC/dev_builds")),
                   ("Rbej Gotham Builds (RPi)",
                    BuildsURL("http://netlir.dk/rbej/builds/Gotham",
                              extractor=RbejLinkExtractor)),
                   ("Rbej Gotham popcornmix Builds (RPi)",
                    BuildsURL("http://netlir.dk/rbej/builds/Gotham%20Popcornmix/",
                              extractor=RbejLinkExtractor)),
                   ("Rbej Frodo Builds (RPi)",
                    BuildsURL("http://netlir.dk/rbej/builds/Frodo",
                              extractor=RbejLinkExtractor)),
                   ("MilhouseVH Builds (RPi)",
                    BuildsURL("http://netlir.dk/rbej/builds/MilhouseVH"))
                  ))

URLS["MilhouseVH Builds"] = URLS["MilhouseVH Builds (RPi)"] # temporary fix
URLS["xbmcnightlybuilds"] = URLS["XBMCNightlyBuilds (Nightly Builds)"] # temp fix to workaround repo rename


if __name__ == "__main__":
    import sys

    def print_links(name, build_url):
        print name
        with build_url.extractor() as parser:
            for link in sorted(set(parser.get_links()), reverse=True):
                print "\t{:25s} {}".format(str(link) + ' *' * (link > INSTALLED_BUILD), link.filename)
        print

    print "Installed build = {}".format(INSTALLED_BUILD)
    print

    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in URLS:
            print '"{}" not in URL list'.format(name)
        else:
            print_links(name, URLS[name])
    else:
        for name, build_url in URLS.items():
            print_links(name, build_url)
