import time
import re
import os
import urlparse
import urllib2
from HTMLParser import HTMLParser
from datetime import datetime

from BeautifulSoup import BeautifulSoup

from constants import CURRENT_BUILD, ARCH, HEADERS

class BuildLink(object):
    """Holds information about an OpenELEC build,
       including how to sort and print them."""

    def __init__(self, baseurl, link, revision, build_date=None):
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
        
        if build_date:
            try:
                self.build_date = datetime.strptime(build_date, '%Y%m%d%H%M%S')
            except TypeError:
                # Work around an issue with datetime.strptime when the script is run a second time.
                self.build_date = datetime(*(time.strptime(build_date, '%Y%m%d%H%M%S')[0:6]))
        else:
            self.build_date = None

        try:
            self.revision = int(revision)
        except ValueError:
            self.revision = revision
        
    def __eq__(self, other):
        return (self.build_date == other.build_date and
                self.revision == other.revision)

    def __hash__(self):
        return hash((self.revision, self.build_date))

    def __lt__(self, other):
        return (self.build_date < other.build_date or
                self.revision < other.revision)

    def __str__(self):
        return '{0} ({1}) {2}'.format(self.revision,
                                      self.build_date.strftime('%d %b %y'),
                                      '*' * (self.revision == CURRENT_BUILD))

class ReleaseLink(BuildLink):
    def __init__(self, baseurl, link, revision):
        BuildLink.__init__(self, baseurl, link, revision)

    def __str__(self):
        return '{0} {1}'.format(self.revision,
                                '*' * (self.revision == CURRENT_BUILD))

class BuildLinkExtractor(object):
    """Class to extract all the build links from the specified URL"""

    BUILD_RE = re.compile(".*OpenELEC-.*{0}-devel-(\d+)-r(\d+).tar.bz2".format(ARCH))
    TAG = 'a'

    def __init__(self, url):
        req = urllib2.Request(url, None, HEADERS)
        self.response = urllib2.urlopen(req)
        self.soup = BeautifulSoup(self.response.read())
        self.url = url

    def get_links(self):  
        for link in self.soup(self.TAG, text=self.BUILD_RE):
            yield self._create_link(link.strip())
            
    def _create_link(self, link):
        build_date, revision = self.BUILD_RE.match(link).groups()
        return BuildLink(self.url, link, revision, build_date)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.response.close()
        
        
class ReleaseLinkExtractor(BuildLinkExtractor):
    
    BUILD_RE = re.compile(".*OpenELEC.*Version:([\d\.]+)")
    TAG = 'td'
        
    def _create_link(self, link):
        version = self.BUILD_RE.match(link).group(1)
        return ReleaseLink("http://releases.openelec.tv/",
                           "OpenELEC-{0}-{1}.tar.bz2".format(ARCH, version), version)

class BuildURL(object):
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
    URL = "http://openelec.thestateofme.com/dev_builds/"
    with BuildLinkExtractor(URL) as parser:
        for link in parser.get_links():
            print link
            
    URL = "http://openelec.tv/get-openelec/viewcategory/8-generic-builds"
    with ReleaseLinkExtractor(URL) as parser:
        for link in parser.get_links():
            print link
            
    URL = "http://sources.openelec.tv/tmp/image"
    with BuildLinkExtractor(URL) as parser:
        for link in parser.get_links():
            print link  
            
            
