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
import html2text

import constants
import openelec


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
                # Work around an issue with datetime.strptime when the script
                # is run a second time.
                dt = time.strptime(_datetime, self.DATETIME_FMT)[0:6]
                self._datetime = datetime(*(dt))

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

    def __repr__(self):
        return "{}('{}', '{}')".format(self.__class__.__name__,
                                       self._datetime, self._version)

    @property
    def date(self):
        return self._datetime.strftime('%d %b %y')

    @property    
    def version(self):
        return self._version


class Release(Build):
    DATETIME_FMT = '%Y-%m-%dT%H:%M:%S'
    MIN_VERSION = [3,95,0]
    tags = None

    def __init__(self, version):
        self.maybe_get_tags()
        if version in self.tags:
            self._has_date = True
            Build.__init__(self, self.tags[version][:19], version)
        else:
            self._has_date = False
        self.release = [int(p) for p in version.split('.')]
        
    def is_valid(self):
        return self._has_date and self.release >= self.MIN_VERSION
    
    __nonzero__ = is_valid

    @classmethod
    def tag_match(cls, tag, attrs):
        return (tag == 'time' or
               ('class' in attrs and attrs['class'] == 'tag-name'))

    @classmethod
    def pagination_match(cls, tag, attrs):
        return (tag == 'div' and
               ('class' in attrs and attrs['class'] == 'pagination'))

    @classmethod
    def get_tags_page_dict(cls, html):
        soup = BeautifulSoup(html, 'html.parser',
                             parse_only=SoupStrainer(cls.tag_match))
        iter_contents = iter(soup.contents)
        return dict((unicode(iter_contents.next().string), tag['datetime'])
                    for tag in iter_contents)
        
    @classmethod
    def maybe_get_tags(cls):
        if cls.tags is None:
            cls.tags = {}
            html = requests.get("http://github.com/OpenELEC/OpenELEC.tv/releases").text
            while True:
                cls.tags.update(cls.get_tags_page_dict(html))
                soup = BeautifulSoup(html, 'html.parser',
                                     parse_only=SoupStrainer(cls.pagination_match))
                next_page_link = soup.find('a', text='Next')
                if next_page_link:
                    href = next_page_link['href']
                    version = [int(p) for p in href.split('=')[-1].split('.')]
                    if version < cls.MIN_VERSION:
                        break
                    html = requests.get(href).text
                else:
                    break


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
                link = urlparse.urlunparse((scheme, "dl.dropbox.com", path,
                                            None, None, None))
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

    def _get_response(self, timeout=None):
        self._response = requests.get(self.url, timeout=timeout)
        if not self._response:
            msg = "Build URL error: status {}".format(self._response.status_code)
            raise BuildURLError(msg)
        return self._response

    def _get_text(self, timeout=None):
        return self._get_response().text

    def _get_json(self, timeout=None):
        return self._get_response().json()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._response is not None:
            self._response.close()

    def __repr__(self):
        return "{}('{}')".format(self.__class__.__name__, self.url)


class BuildLinkExtractor(BaseExtractor):
    """Class to extract all the build links from the specified URL"""

    BUILD_RE = (".*OpenELEC.*-{arch}-(?:\d+\.\d+-|)[a-zA-Z]+-(\d+)"
                "-r\d+[a-z]*-g([0-9a-z]+)\.tar(|\.bz2)")
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
    BUILD_RE = ("OpenELEC-{arch}-(?:\d+\.\d+-|)"
                "Milhouse-(\d+)-(?:r|%23)(\d+[a-z]*)-g[0-9a-z]+\.tar(|\.bz2)")


class BuildInfo(object):
    def __init__(self, summary, details=None):
        self.summary = summary
        self.details = details

    def __str__(self):
        return self.summary


class BuildDetailsExtractor(BaseExtractor):
    def get_text(self, timeout=None):
        return ""


class MilhouseBuildDetailsExtractor(BuildDetailsExtractor):
    def get_text(self, timeout=None):
        soup = BeautifulSoup(self._get_text(timeout), 'html.parser')
        pid = urlparse.parse_qs(urlparse.urlparse(self.url).query)['pid'][0]
        post_div_id = "pid_{}".format(pid)
        post = soup.find('div', 'post-body', id=post_div_id)

        text_maker = html2text.HTML2Text()
        text_maker.ignore_links = True
        text_maker.ul_item_mark = '-'

        text = text_maker.handle(unicode(post))

        text = re.search(r"(Build Highlights:.*)", text, re.DOTALL).group(1)
        text = re.sub(r"(Build Highlights:)", r"[B]\1[/B]", text)
        text = re.sub(r"(Build Details:)", r"[B]\1[/B]", text)

        return text


class BuildInfoExtractor(BaseExtractor):
    def get_info(self, timeout=None):
        return {}


class MilhouseBuildInfoExtractor(BuildInfoExtractor):
    URL_FMT = "http://forum.kodi.tv/showthread.php?tid={}"
    R = re.compile("#(\d{4}[a-z]?).*?\((.+)\)")

    def _get_info(self, soup):
        for post in soup.find_all('div', 'post-body', limit=2):
            for ul in post('ul'):
                for li in ul('li'):
                    m = self.R.match(li.get_text())
                    if m:
                        url = li.find('a', text="Release post")['href']
                        yield m.group(1), BuildInfo(m.group(2),
                                                    MilhouseBuildDetailsExtractor(url))

    def get_info(self, timeout=None):
        soup = BeautifulSoup(self._get_text(timeout), 'html.parser')
        return dict(self._get_info(soup))

    @classmethod
    def from_thread_id(cls, thread_id):
        url = cls.URL_FMT.format(thread_id)
        return cls(url)


def get_milhouse_build_info_extractors():
    for thread_id in (224025, 231092):
        yield MilhouseBuildInfoExtractor.from_thread_id(thread_id)


class CommitInfoExtractor(BuildInfoExtractor):
    URL = "https://api.github.com/repositories/1093060/commits?per_page=100"

    def get_info(self, timeout=None):
        return dict((commit['sha'][:7],
                     BuildInfo(commit['commit']['message'].split('\n\n')[0], None))
                     for commit in self._get_json(timeout))


class BuildsURL(object):
    def __init__(self, url, subdir=None, extractor=BuildLinkExtractor,
                 info_extractors=[BuildInfoExtractor()]):
        self.url = url
        if subdir:
            self.add_subdir(subdir)
        
        self._extractor = extractor
        self.info_extractors = info_extractors

    def extractor(self):
        return self._extractor(self.url)
        
    def add_subdir(self, subdir):
        self._add_slash()
        self.url = urlparse.urljoin(self.url, subdir)
        self._add_slash()

    def _add_slash(self):
        if not self.url.endswith('/'):
            self.url += '/'

    def __str__(self):
        return self.url

    def __repr__(self):
        return "{}('{}')".format(self.__class__.__name__, self.url)


def get_installed_build():
    DEVEL_RE = "devel-(\d+)-r\d+-g([a-z0-9]+)"

    if openelec.OS_RELEASE['NAME'] == "OpenELEC":
        version = openelec.OS_RELEASE['VERSION']
        if 'MILHOUSE_BUILD' in openelec.OS_RELEASE:
            DEVEL_RE = "devel-(\d+)-[r#](\d+)"
    else:
        # For testing on a non OpenELEC machine
        version = 'devel-20150503135721-r20764-gbfd3782'

    m = re.match(DEVEL_RE, version)
    if m:
        return Build(*m.groups())
    else:
        # A full release is installed.
        return Release(version)


def sources(arch):
    _sources = OrderedDict()

    builds_url = BuildsURL("http://snapshots.openelec.tv",
                           info_extractors=[CommitInfoExtractor()])
    _sources["Official Snapshot Builds"] = builds_url

    builds_url = BuildsURL("http://milhouse.openelec.tv/builds/master",
                           subdir=arch.split('.')[0],
                           extractor=MilhouseBuildLinkExtractor,
                           info_extractors=list(get_milhouse_build_info_extractors()))
    _sources["Milhouse Builds"] = builds_url

    if openelec.debug_system_partition():
        builds_url = BuildsURL("http://milhouse.openelec.tv/builds/debug",
                               subdir=arch.split('.')[0],
                               extractor=MilhouseBuildLinkExtractor)
        _sources["Milhouse Builds (Debug)"] = builds_url

    if arch.startswith("RPi"):
        builds_url = BuildsURL("http://resources.pichimney.com/OpenELEC/dev_builds",
                               info_extractors=[CommitInfoExtractor()])
        _sources["Chris Swan RPi Builds"] = builds_url

    _sources["Official Releases"] = BuildsURL("http://openelec.mirrors.uk2.net",
                                              extractor=OfficialReleaseLinkExtractor)
    _sources["Official Archive"] = BuildsURL("http://archive.openelec.tv",
                                             extractor=ReleaseLinkExtractor)

    builds_url = BuildsURL("http://openelec-dualaudio.subcarrier.de/OpenELEC-DualAudio/",
                           subdir=arch,
                           extractor=DualAudioReleaseLinkExtractor)
    _sources["DarkAngel2401 Dual Audio Builds"] = builds_url

    return _sources


def latest_build(arch, source, timeout=None):
    build_sources = sources(arch)
    try:
        build_url = build_sources[source]
    except KeyError:
        pass
    else:
        with build_url.extractor() as parser:
            builds = sorted(parser.get_links(arch, timeout), reverse=True)

        try:
            return builds[0]
        except IndexError:
            return None


if __name__ == "__main__":
    import sys
    
    installed_build = get_installed_build()

    def get_info(build_url):
        info = {}
        for info_extractor in build_url.info_extractors:
            try:
                with info_extractor:
                    info.update(info_extractor.get_info())
            except Exception as e:
                print str(e)
        return info

    def print_links(name, build_url, arch):
        info = get_info(build_url)
        print name
        try:
            with build_url.extractor() as parser:
                for link in sorted(set(parser.get_links(arch)), reverse=True):
                    try:
                        summary = info[link.version]
                    except KeyError:
                        summary = ""
                    print "\t{:25s} {}".format(str(link) + ' *' * (link > installed_build),
                                               summary)
        except (requests.RequestException, BuildURLError) as e:
            print str(e)
        print

    print "Installed build = {}".format(installed_build)
    print

    urls = sources(openelec.ARCH)

    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in urls:
            print '"{}" not in URL list'.format(name)
        else:
            print_links(name, urls[name], openelec.ARCH)
    else:
        for name, build_url in urls.items():
            print_links(name, build_url, openelec.ARCH)
