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

import openelec, funcs, log


timeout = None
arch = openelec.ARCH
date_fmt = '%d %b %y'


class BuildURLError(Exception):
    pass


class Build(object):
    """Holds information about an OpenELEC build and defines how to compare them,
       produce a unique hash for dictionary keys, and print them.
    """
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
        return '{} ({})'.format(self.version, self.date)

    def __repr__(self):
        return "{}('{}', '{}')".format("Build",
                                       self._datetime.strftime(self.DATETIME_FMT),
                                       self.version)

    @property
    def date(self):
        return self._datetime.strftime(date_fmt)

    @property
    def version(self):
        return self._version


class Release(Build):
    """Subclass of Build for official releases.

       Has additional methods for retrieving datetime information from the git tags.
    """
    DATETIME_FMT = '%Y-%m-%dT%H:%M:%S'
    MIN_VERSION = [3,95,0]
    tags = None

    def __init__(self, version):
        self.release_str = version
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
        return (tag == 'relative-time' or
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
            releases_url = "http://github.com/{dist}/{dist}.tv/tags".format(
                                dist=openelec.dist())
            html = requests.get(releases_url).text
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

    def __repr__(self):
        return "{}('{}')".format("Release", self.release_str)


class BuildLinkBase(object):
    """Base class for links to builds"""
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
        response = requests.get(self.url, stream=True, timeout=timeout,
                                headers={'Accept-Encoding': None})
        try:
            self.size = int(response.headers['Content-Length'])
        except KeyError:
            self.size = 0

        # Get the actual filename
        self.filename = unquote(os.path.basename(urlparse.urlparse(response.url).path))

        name, ext = os.path.splitext(self.filename)
        self.tar_name = self.filename if ext == '.tar' else name
        self.compressed = ext == '.bz2'

        return response.raw


class BuildLink(Build, BuildLinkBase):
    """Holds information about a link to an OpenELEC build."""
    def __init__(self, baseurl, link, datetime_str, revision):
        BuildLinkBase.__init__(self, baseurl, link)
        Build.__init__(self, datetime_str, version=revision)


class ReleaseLink(Release, BuildLinkBase):
    """Class for links to OpenELEC release downloads."""
    def __init__(self, baseurl, link, release):
        BuildLinkBase.__init__(self, baseurl, link)
        Release.__init__(self, release)


class BaseExtractor(object):
    """Base class for all extractors."""
    url = None

    def __init__(self, url=None):
        if url is not None:
            self.url = url

    def _response(self):
        response = requests.get(self.url, timeout=timeout)
        if not response:
            msg = "Build URL error: status {}".format(response.status_code)
            raise BuildURLError(msg)
        return response

    def _text(self):
        return self._response().text

    def _json(self):
        return self._response().json()

    def __repr__(self):
        return "{}('{}')".format(self.__class__.__name__, self.url)


class BuildLinkExtractor(BaseExtractor):
    """Base class for extracting build links from a URL"""
    BUILD_RE = (".*{dist}.*-{arch}-(?:\d+\.\d+-|)[a-zA-Z]+-(\d+)"
                "-r\d+[a-z]*-g([0-9a-z]+)\.tar(|\.bz2)")
    CSS_CLASS = None

    def __iter__(self):
        html = self._text()
        args = ['a']
        if self.CSS_CLASS is not None:
            args.append(self.CSS_CLASS)

        self.build_re = re.compile(self.BUILD_RE.format(dist=openelec.dist(), arch=arch), re.I)

        soup = BeautifulSoup(html, 'html.parser',
                             parse_only=SoupStrainer(*args, href=self.build_re))

        for link in soup.contents:
            l = self._create_link(link)
            if l:
                yield l

    def _create_link(self, link):
        href = link['href']
        return BuildLink(self.url, href, *self.build_re.match(href).groups()[:2])


class DropboxBuildLinkExtractor(BuildLinkExtractor):
    CSS_CLASS = 'filename-link'


class ReleaseLinkExtractor(BuildLinkExtractor):
    """Class to extract release links from a URL.

       Overrides _create_link to return a ReleaseLink for each link.
    """
    BUILD_RE = ".*{dist}.*-{arch}-([\d\.]+)\.tar(|\.bz2)"
    BASE_URL = None

    def _create_link(self, link):
        href = link['href']
        baseurl = self.BASE_URL if self.BASE_URL is not None else self.url
        return ReleaseLink(baseurl, href, self.build_re.match(href).group(1))


class OfficialReleaseLinkExtractor(ReleaseLinkExtractor):
    BASE_URL = "http://releases.{dist}.tv".format(dist=openelec.dist())


class DualAudioReleaseLinkExtractor(ReleaseLinkExtractor):
    BUILD_RE = ".*{dist}-{arch}.DA-([\d\.]+)\.tar(|\.bz2)"


class MilhouseBuildLinkExtractor(BuildLinkExtractor):
    BUILD_RE = ("{dist}-{arch}-(?:\d+\.\d+-|)"
                "Milhouse-(\d+)-(?:r|%23)(\d+[a-z]*)-g[0-9a-z]+\.tar(|\.bz2)")


class BuildInfo(object):
    """Class to hold the short summary of a build and the full details."""
    def __init__(self, summary, details=None):
        self.summary = summary
        self.details = details

    def __str__(self):
        return self.summary


class BuildDetailsExtractor(BaseExtractor):
    """Default class for extracting build details which returns an empty string."""
    def get_text(self):
        return ""


class MilhouseBuildDetailsExtractor(BuildDetailsExtractor):
    """Class for extracting the full build details for a Milhouse build.
       from the release post on the Kodi forum.
    """
    def get_text(self):
        soup = BeautifulSoup(self._text(), 'html.parser')
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
    """Default build info extractor class for all build sources which just creates
       an empty dictionary."""
    def get_info(self):
        return {}


class MilhouseBuildInfoExtractor(BuildInfoExtractor):
    """Class for creating a dictionary of BuildInfo objects for Milhouse builds
       keyed on the build version."""
    URL_FMT = "http://forum.kodi.tv/showthread.php?tid={}"
    R = re.compile("#(\d{4}[a-z]?).*?\((.+)\)")

    def _get_info(self, soup):
        for post in soup.find_all('div', 'post-body', limit=3):
            for ul in post('ul'):
                for li in ul('li'):
                    m = self.R.match(li.get_text())
                    if m:
                        url = li.find('a', text="Release post")['href']
                        yield m.group(1), BuildInfo(m.group(2),
                                                    MilhouseBuildDetailsExtractor(url))

    def get_info(self):
        soup = BeautifulSoup(self._text(), 'html.parser')
        return dict(self._get_info(soup))

    @classmethod
    def from_thread_id(cls, thread_id):
        """Create a Milhouse build info extractor from the thread id number."""
        url = cls.URL_FMT.format(thread_id)
        return cls(url)


def get_milhouse_build_info_extractors():
    if openelec.dist() == "openelec":
        if arch.startswith("RPi"):
            threads = [224025, 231092, 250817]
        else:
            threads = [238393]
    elif openelec.dist() == "libreelec":
        if arch.startswith("RPi"):
            threads = [269814, 298461]
        else:
            threads = [269815, 298462]

    for thread_id in threads:
        yield MilhouseBuildInfoExtractor.from_thread_id(thread_id)


class CommitInfoExtractor(BuildInfoExtractor):
    """Class used by development build sources for extracting the git commit messages
       for a commit hash as the summary. Full build details are set to None."""
    url = "https://api.github.com/repositories/1093060/commits?per_page=100"

    def get_info(self):
        return dict((commit['sha'][:7],
                     BuildInfo(commit['commit']['message'].split('\n\n')[0], None))
                     for commit in self._json())


class BuildsURL(object):
    """Class representing a source of builds."""
    def __init__(self, url, subdir=None, extractor=BuildLinkExtractor,
                 info_extractors=[BuildInfoExtractor()]):
        self.url = url
        if subdir:
            self.add_subdir(subdir)

        self._extractor = extractor
        self.info_extractors = info_extractors

    def builds(self):
        return sorted(self._extractor(self.url), reverse=True)

    def __iter__(self):
        return iter(self.builds())

    def latest(self):
        """Return the most recent build or None if no builds are available."""
        builds = self.builds()
        try:
            return builds[0]
        except IndexError:
            return None

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


class MilhouseBuildsURL(BuildsURL):
    def __init__(self, subdir="master"):
        self.subdir = subdir
        url = "http://milhouse.{dist}.tv/builds/".format(dist=openelec.dist().lower())
        super(MilhouseBuildsURL, self).__init__(
            url, os.path.join(subdir, arch.split('.')[0]),
            MilhouseBuildLinkExtractor, list(get_milhouse_build_info_extractors()))

    def __repr__(self):
        return "{}('{}')".format(self.__class__.__name__, self.subdir)


dual_audio_builds = BuildsURL("http://openelec-dualaudio.subcarrier.de/OpenELEC-DualAudio/",
                              subdir=arch, extractor=DualAudioReleaseLinkExtractor)


def get_installed_build():
    """Return the currently installed build object."""
    DEVEL_RE = "devel-(\d+)-r\d+-g([a-z0-9]+)"
    if 'MILHOUSE_BUILD' in openelec.OS_RELEASE:
        DEVEL_RE = "devel-(\d+)-[r#](\d{4}[a-z]?)"

    if openelec.OS_RELEASE['NAME'] in ("OpenELEC", "LibreELEC"):
        version = openelec.OS_RELEASE['VERSION']
    else:
        # For testing on a non OpenELEC machine
        version = 'devel-20150503135721-r20764-gbfd3782'

    m = re.match(DEVEL_RE, version)
    if m:
        return Build(*m.groups())
    else:
        # A full release is installed.
        return Release(version)


def sources():
    """Return an ordered dictionary of the sources as BuildsURL objects.
       Only return sources which are relevant for the system.
       The GUI will show the sources in the order defined here.
    """
    _sources = OrderedDict()
    if openelec.OS_RELEASE['NAME'] == "OpenELEC":
        builds_url = BuildsURL("http://snapshots.openelec.tv",
                            info_extractors=[CommitInfoExtractor()])
        _sources["Official Snapshot Builds"] = builds_url

        if arch.startswith("RPi"):
            builds_url = BuildsURL("http://resources.pichimney.com/OpenELEC/dev_builds",
                                   info_extractors=[CommitInfoExtractor()])
            _sources["Chris Swan RPi Builds"] = builds_url

        _sources["Official Releases"] = BuildsURL(
            "http://{dist}.mirrors.uk2.net".format(dist=openelec.dist()),
            extractor=OfficialReleaseLinkExtractor)

    _sources["Official Archive"] = BuildsURL(
        "http://archive.{dist}.tv".format(dist=openelec.dist()), extractor=ReleaseLinkExtractor)

    _sources["Milhouse Builds"] = MilhouseBuildsURL()

    if openelec.debug_system_partition():
        _sources["Milhouse Builds (debug)"] = MilhouseBuildsURL(subdir="debug")

    return _sources


def latest_build(source):
    """Return the most recent build for the provided source name or None if
       there is an error. This is used by the service to check for a new build.
    """
    build_sources = sources()
    try:
        build_url = build_sources[source]
    except KeyError:
        return None
    else:
        return build_url.latest()


@log.with_logging(msg_error="Unable to create build object from the notify file")
def get_build_from_notify_file():
    selected = funcs.read_notify_file()
    if selected:
        source, build_repr = selected
        return source, eval(build_repr)


def main():
    """Test function to print all available builds when executing the module."""
    import sys

    installed_build = get_installed_build()

    def get_info(build_url):
        info = {}
        for info_extractor in build_url.info_extractors:
            try:
                info.update(info_extractor.get_info())
            except Exception as e:
                print str(e)
        return info

    def print_links(name, build_url):
        info = get_info(build_url)
        print name
        try:
            for link in build_url:
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

    urls = sources()

    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in urls:
            print '"{}" not in URL list'.format(name)
        else:
            print_links(name, urls[name])
    else:
        for name, build_url in urls.items():
            print_links(name, build_url)


if __name__ == "__main__":
    main()
