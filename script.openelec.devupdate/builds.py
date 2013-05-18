import time
import re
import os
import urlparse
import urllib2
from datetime import datetime
from email.utils import parsedate

from BeautifulSoup import BeautifulSoup

from constants import CURRENT_BUILD, ARCH, HEADERS

class BuildLink(object):
    """Holds information about an OpenELEC build,
       including how to sort and print them."""
       
    DATETIME_FMT = '%Y%m%d%H%M%S'

    def __init__(self, baseurl, link, revision, build_date_str=None):
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

        try:
            self.revision = int(revision)
        except ValueError:
            self.revision = revision
            
        self.build_date_str = build_date_str
            
        self._set_build_datetime()
            
    def _set_build_datetime(self):
        if self.build_date_str is None:
            self.build_datetime = None
        else:
            try:
                self.build_datetime = datetime.strptime(self.build_date_str, self.DATETIME_FMT)
            except TypeError:
                # Work around an issue with datetime.strptime when the script is run a second time.
                self.build_datetime = datetime(*(time.strptime(self.build_date_str, self.DATETIME_FMT)[0:6]))
        
    def __eq__(self, other):
        return (self.build_datetime == other.build_datetime and
                self.revision == other.revision)

    def __hash__(self):
        return hash((self.revision, self.build_datetime))

    def __lt__(self, other):
        return (self.build_datetime < other.build_datetime or
                self.revision < other.revision)

    def __str__(self):
        return '{0} ({1}) {2}'.format(self.revision,
                                      self.build_datetime.strftime('%d %b %y'),
                                      '*' * (self.revision == CURRENT_BUILD))
        
class ReleaseLink(BuildLink):
    DATETIME_FMT = None
    BASEURL = "http://releases.openelec.tv/"
    
    def __init__(self, version):
        link = "OpenELEC-{0}-{1}.tar.bz2".format(ARCH, version)
        BuildLink.__init__(self, self.BASEURL, link, version)
    
    def _set_build_datetime(self):
        req = urllib2.Request(self.url, None, HEADERS)
        rf = urllib2.urlopen(req)
        self.build_date_str = rf.headers.getheader('Last-Modified')
        # RFC 2822 format
        self.build_datetime = datetime(*parsedate(self.build_date_str)[:7])


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
        build_date_str, revision = self.BUILD_RE.match(href).groups()
        return BuildLink(self._url, href.strip(), revision, build_date_str)

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
            all_versions = [version[:-1] + str(i) for i in range(int(version[-1]), -1, -1)]
            for v in all_versions:
                yield ReleaseLink(v)


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

if __name__ == "__main__":
    
    URL = "http://openelec.tv/get-openelec/viewcategory/8-generic-builds"
    with ReleaseLinkExtractor(URL) as parser:
        links = list(parser.get_links())
        for link in links:
            print link

    latest_release = links[0]
    print
    
    for URL in ("http://sources.openelec.tv/tmp/image",
                "http://openelec.thestateofme.com/dev_builds/?O=D"):
        with BuildLinkExtractor(URL) as parser:
            for link in parser.get_links():
                print link, link > latest_release
        print

    with DropboxLinkExtractor("https://www.dropbox.com/sh/3uhc063czl2eu3o/2r8Ng7agdD/OpenELEC-XBMC-13/Latest/kernel.3.9") as parser:
        for link in parser.get_links():
            print link, link > latest_release