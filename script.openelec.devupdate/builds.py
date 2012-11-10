import time
import re
import os
import urlparse
import urllib2
from HTMLParser import HTMLParser
from datetime import datetime

from constants import CURRENT_BUILD, ARCH, HEADERS

class BuildLink(object):
    """Holds information about an OpenELEC build,
       including how to sort and print them."""

    def __init__(self, baseurl, link, build_date, revision):
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
            self.build_date = datetime.strptime(build_date, '%Y%m%d%H%M%S')
        except TypeError:
            # Work around an issue with datetime.strptime when the script is run a second time.
            self.build_date = datetime(*(time.strptime(build_date, '%Y%m%d%H%M%S')[0:6]))
        self.revision = int(revision)
        
    def __eq__(self, other):
        return (self.build_date == other.build_date and
                self.revision == other.revision)

    def __hash__(self):
        return hash((self.revision, self.build_date))

    def __lt__(self, other):
        return self.build_date < other.build_date

    def __str__(self):
        return '{0} ({1}) {2}'.format(self.revision,
                                      self.build_date.strftime('%d %b %y'),
                                      '*' * (self.revision == CURRENT_BUILD))


class BuildLinkExtractor(HTMLParser):
    """Class to extract all the build links from the specified URL"""

    BUILD_RE = re.compile(".*OpenELEC-.*{0}-devel-(\d+)-r(\d+).tar.bz2".format(ARCH))

    def __init__(self, url):
        HTMLParser.__init__(self)
  
        req = urllib2.Request(url, None, HEADERS)
        self.response = urllib2.urlopen(req)
        self.html = self.response.read()
        self.url = url
        
        self.links = []

    def get_links(self):
        self.feed(self.html)
        # Remove duplicates and sort so that the most recent build is first.
        return list(sorted(set(self.links), reverse=True))

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for attr, value in attrs:
                if attr == 'href':
                    m = self.BUILD_RE.match(value)
                    if m:
                        self.links.append(BuildLink(self.url,
                                                    value,
                                                    *m.groups()))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.response.close()
