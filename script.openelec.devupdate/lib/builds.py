import time
import re
import os
import urlparse
import urllib2
import socket
from datetime import datetime

from BeautifulSoup import BeautifulSoup, SoupStrainer

from constants import ARCH, HEADERS


class Build(object):
    """Holds information about an OpenELEC build,
       including how to sort and print them."""
       
    DATETIME_FMT = '%Y%m%d%H%M%S'

    def __init__(self, datetime_str, version):
        self.version = version
        try:
            self._version = [int(i) for i in version.split('.')]
        except ValueError:
            self._version = version  
        self.datetime_str = datetime_str

        if datetime_str is None:
            self._datetime = None
        else:
            try:
                self._datetime = datetime.strptime(datetime_str, self.DATETIME_FMT)
            except TypeError:
                # Work around an issue with datetime.strptime when the script is run a second time.
                self._datetime = datetime(*(time.strptime(datetime_str, self.DATETIME_FMT)[0:6]))

    def __eq__(self, other):
        return (self._version, self._datetime) == (other._version, other._datetime)

    def __hash__(self):
        return hash((self.version, self.datetime_str))

    def __lt__(self, other):
        return self._datetime < other._datetime
    
    def __gt__(self, other):
        return self._datetime > other._datetime

    def __str__(self):
        return '{} ({})'.format(self.version,
                                self._datetime.strftime('%d %b %y'))
        
        
class Release(Build):
    DATETIME_FMT = '%Y-%m-%d %H:%M:%S'
    soup = None

    def __init__(self, version):
        self.maybe_get_tags()
        datetime_str = self.soup.find('a', href=re.compile(version)).time['title']
        Build.__init__(self, datetime_str, version)
        
    @classmethod
    def maybe_get_tags(cls):
        if cls.soup is None:
            req = urllib2.Request("http://github.com/OpenELEC/OpenELEC.tv/tags", None, HEADERS)
            html = urllib2.urlopen(req).read()
            cls.soup = BeautifulSoup(html,
                                     SoupStrainer('a', href=re.compile("/OpenELEC/OpenELEC.tv/releases")))


class RbejBuild(Build):
    DATETIME_FMT = '%d.%m.%Y'
    
    
class AbstractBuildLink(object):
    
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


class BuildLink(Build, AbstractBuildLink):
    """Holds information about a link to an OpenELEC build."""

    def __init__(self, baseurl, link, revision, datetime_str=None):
        Build.__init__(self, datetime_str, version=revision)

        scheme, netloc, path = urlparse.urlparse(link)[:3]
        if not scheme:
            self.filename = link
            # Construct the full url
            self.url = urlparse.urljoin(baseurl, link)
        else:
            if netloc == "www.dropbox.com":
                link = urlparse.urlunparse((scheme, "dl.dropbox.com", path, None, None, None))
            self.url = link
            # Extract the file name part
            self.filename = os.path.basename(link)

        self._set_info()


class ReleaseLink(Release, AbstractBuildLink):
    BASEURL = "http://releases.openelec.tv"
    
    def __init__(self, version, baseurl=None, filename=None):
        if baseurl is None:
            self.baseurl = self.BASEURL
        else:
            self.baseurl = baseurl

        if filename is None:
            filename = "OpenELEC-{}-{}.tar.bz2".format(ARCH, version)
            
        # Check if the link exists with or without the .bz2 extension.
        self._exists = False
        for f in (filename, os.path.splitext(filename)[0]):
            url = self._test_url(f)
            if url:
                self.filename = f
                self.url = url
                self._exists = True
                self._set_info()
                break
        
        Release.__init__(self, version)
        
    def _test_url(self, f):
        url = urlparse.urljoin(self.baseurl, f)
        req = urllib2.Request(url, None, HEADERS)
        try:
            urllib2.urlopen(req)
        except (urllib2.HTTPError, socket.error):
            return None
        else:
            return url
        
    def exists(self):
        return self._exists


class RbejBuildLink(RbejBuild, AbstractBuildLink):
    def __init__(self, baseurl, link, version, datetime_str):
        RbejBuild.__init__(self, datetime_str, version)
        self.filename = os.path.basename(link)
        self.url = urlparse.urljoin(baseurl, link)
        
        self._set_info()


class BuildLinkExtractor(object):
    """Class to extract all the build links from the specified URL"""

    BUILD_RE = re.compile(".*OpenELEC.*-{0}-devel-(\d+)-r(\d+).tar(|.bz2)".format(ARCH))
    TAG = 'a'
    CLASS = None
    HREF = BUILD_RE
    TEXT = None

    def __init__(self, url):
        req = urllib2.Request(url, None, HEADERS)
        self._response = urllib2.urlopen(req)
        self._url = url
        html = self._response.read()
        soup = BeautifulSoup(html, parseOnlyThese=SoupStrainer(self.TAG,
                                                               self.CLASS,
                                                               href=self.HREF,
                                                               text=self.TEXT))
        self._links = soup.contents

    def get_links(self):
        for link in self._links:
            yield self._create_link(link)

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
            all_versions = [version[:-1] + str(i) for i in range(int(version[-1]), -1, -1)]
            for v in all_versions:
                rl = ReleaseLink(v)
                if rl.exists():
                    yield rl


class ArchiveLinkExtractor(BuildLinkExtractor):

    BUILD_RE = re.compile(".*OpenELEC.*-{0}-([\d\.]+).tar(|.bz2)".format(ARCH))
    TEXT = BUILD_RE

    def _create_link(self, link):
        version = self.BUILD_RE.match(link).group(1)
        return ReleaseLink(version, self._url, link)


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


# Create a INSTALLED_BUILD object for comparison
try:
    VERSION = open('/etc/version').read().rstrip()
except IOError:
    VERSION = '3.0.1'

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
    
    
URLS = {"Official Daily Builds":
            BuildsURL("http://sources.openelec.tv/tmp/image"),
        "Official Releases":
            BuildsURL("http://openelec.tv/get-openelec/viewcategory/8-generic-builds",
                      extractor=ReleaseLinkExtractor),
        "Chris Swan (RPi)":
            BuildsURL("http://resources.pichimney.com/OpenELEC/dev_builds"),
        "vicbitter Gotham Builds":
            BuildsURL("https://www.dropbox.com/sh/3uhc063czl2eu3o/2r8Ng7agdD/OpenELEC-XBMC-13/Latest/kernel.3.9",
                      extractor=DropboxLinkExtractor),
        "Official Archive":
            BuildsURL("http://archive.openelec.tv", extractor=ArchiveLinkExtractor),
        "Rbej Gotham Builds (RPi)":
            BuildsURL("http://netlir.dk/rbej/builds/Gotham",
                      extractor=RbejLinkExtractor),
        "Rbej Frodo Builds (RPi)":
            BuildsURL("http://netlir.dk/rbej/builds/Frodo",
                      extractor=RbejLinkExtractor)
        }


if __name__ == "__main__":
    print INSTALLED_BUILD
    print
    for name, build_url in URLS.iteritems():
        print name
        with build_url.extractor() as parser:
            for link in sorted(parser.get_links(), reverse=True):
                print "\t{} {}".format(link, '*' * (link > INSTALLED_BUILD))
        print
