import time
import re
import os
import urlparse
import urllib2
from datetime import datetime
from email.utils import parsedate

from BeautifulSoup import BeautifulSoup

from constants import VERSION, ARCH, HEADERS


class Build(object):
    """Holds information about an OpenELEC build,
       including how to sort and print them."""
       
    DATETIME_FMT = '%Y%m%d%H%M%S'

    def __init__(self, datetime_str, version):
        self.version = version
        self._version = [int(i) for i in version.split('.')]  
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
        return (self._version, self._datetime.date()) == (other._version, other._datetime.date())

    def __hash__(self):
        return hash((self.version, self.datetime_str))

    def __lt__(self, other):
        return self._datetime.date() < other._datetime.date() or self._version < other._version
    
    def __gt__(self, other):
        return self._datetime.date() > other._datetime.date() or self._version > other._version

    def __str__(self):
        return '{} ({})'.format(self.version,
                                self._datetime.strftime('%d %b %y'))
        
        
class Release(Build):
    DATETIME_FMT = '%Y-%m-%d %H:%M:%S'
    
    soup = BeautifulSoup(urllib2.urlopen("http://github.com/OpenELEC/OpenELEC.tv/tags").read())
    TAGS = soup.find('table', 'tag-list')
    
    def __init__(self, version):
        datetime_str = self.TAGS.find('div', 'tag-info', text=version).findPrevious('time')['title']
        Build.__init__(self, datetime_str, version)
    

class BuildLink(Build):
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


class ReleaseLink(Release):
    BASEURL = "http://releases.openelec.tv/"
    
    def __init__(self, version):
        self.filename = "OpenELEC-{}-{}.tar.bz2".format(ARCH, version)
        self.url = urlparse.urljoin(self.BASEURL, self.filename)
        Release.__init__(self, version)


class BuildLinkExtractor(object):
    """Class to extract all the build links from the specified URL"""

    BUILD_RE = re.compile(".*OpenELEC.*-{0}-devel-(\d+)-r(\d+).tar.bz2".format(ARCH))
    TAG = 'a'
    CLASS = None
    HREF = BUILD_RE
    TEXT = None

    def __init__(self, url):
        req = urllib2.Request(url, None, HEADERS)
        self._response = urllib2.urlopen(req)
        self._url = url
        soup = BeautifulSoup(self._response.read())
        self._links = soup(self.TAG, self.CLASS, href=self.HREF, text=self.TEXT)

    def get_links(self):  
        for link in self._links:
            yield self._create_link(link)

    def _create_link(self, link):
        href = link['href']
        datetime_str, revision = self.BUILD_RE.match(href).groups()
        return BuildLink(self._url, href.strip(), revision, datetime_str)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._response.close()


class DropboxLinkExtractor(BuildLinkExtractor):

    CLASS = 'filename-link'
        
        
class ReleaseLinkExtractor(BuildLinkExtractor):
    
    BUILD_RE = re.compile(".*OpenELEC.*Version:([\d\.]+)")
    TAG = 'tr'
    TEXT = BUILD_RE
    HREF = None
    
    #DATE_RE = re.compile("(\d{4}-\d{2}-\d{2})")
    
    def get_links(self):
        for link in self._links:    
            version = self.BUILD_RE.match(link).group(1)
            #build_date = link.findNext(text=self.DATE_RE).strip()
            
            # Look for older releases and get the upload dates.
            all_versions = [version[:-1] + str(i) for i in range(int(version[-1]), -1, -1)]
            for v in all_versions:
                rl = ReleaseLink(v)
                req = urllib2.Request(rl.url, None, HEADERS)
                try:
                    rf = urllib2.urlopen(req)
                except urllib2.HTTPError:
                    pass
                else:
                    yield rl


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
m = re.search("devel-(\d+)-r(\d+)", VERSION)
if m:
    INSTALLED_BUILD = Build(*m.groups())
else:
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
                      extractor=DropboxLinkExtractor)
        }


if __name__ == "__main__":
    for name, build_url in URLS.iteritems():
        print name
        with build_url.extractor() as parser:
            for link in parser.get_links():
                print "\t{} {}".format(link, '*' * (link > INSTALLED_BUILD))
        print
