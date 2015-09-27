#! /usr/bin/python

import os
from datetime import datetime
import sqlite3

from log import with_logging

try:
    import addon
except ImportError:
    pass
else:
    HISTORY_FILE = os.path.join(addon.data_path, 'builds.db')


def maybe_create_database():
    with sqlite3.connect(HISTORY_FILE) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS builds
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                         version TEXT NOT NULL, marked INTEGER default 0, comments TEXT,
                         UNIQUE(source, version))''')
        
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS source_version
                        ON builds (source, version)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS installs
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         build_id INTEGER REFERENCES builds(id),
                         timestamp TIMESTAMP NOT NULL)''')


@with_logging("Added install {}|{} to database",
              "Failed to add install {}|{} to database")
def add_install(source, build):
    maybe_create_database()
    with sqlite3.connect(HISTORY_FILE) as conn:
        conn.execute('''INSERT OR IGNORE INTO builds (source, version)
                        VALUES (?, ?)''', (source, build.version))

        build_id = conn.execute('''SELECT last_insert_rowid()
                                   FROM builds''').fetchone()[0]
        if build_id == 0:
            build_id = get_build_id(source, build.version)

        conn.execute('''INSERT INTO installs (build_id, timestamp)
                        VALUES (?, ?)''', (build_id, datetime.now()))


def get_build_id(source, version):
    with sqlite3.connect(HISTORY_FILE) as conn:
        return conn.execute('''SELECT id FROM builds WHERE source = ? AND version = ?''',
                            (source, version)).fetchone()[0]


@with_logging("Retrieved install history for source {}",
              "Failed to retrieve install history for source {}")
def get_source_install_history(source):
    with sqlite3.connect(HISTORY_FILE, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
        return conn.execute('''SELECT version, timestamp
                               FROM installs
                               JOIN builds ON builds.id = build_id
                               WHERE source = ?''', (source,)).fetchall()


def get_full_install_history():
    with sqlite3.connect(HISTORY_FILE, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
        return conn.execute('''SELECT source, version, timestamp
                               FROM installs
                               JOIN builds ON builds.id = build_id''').fetchall()


def is_previously_installed(source, build):
    with sqlite3.connect(HISTORY_FILE) as conn:
        return bool(conn.execute('''SELECT COUNT(*) FROM installs WHERE
                                    source = ? AND version = ?''',
                                 (source, build.version)).fetchone()[0])


if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    from funcs import add_deps_to_path
    add_deps_to_path()
    import builds

    parser = ArgumentParser(description='Print install history',
                            formatter_class=RawTextHelpFormatter)
    parser.add_argument(
        'dbpath', nargs='?',
        default="/storage/.kodi/userdata/addon_data/script.openelec.devupdate/builds.db",
        help="path to the install history database \n (default: %(default)s)")

    args = parser.parse_args()

    HISTORY_FILE = args.dbpath

    for source in builds.sources():
        history = get_source_install_history(source)
        if history:
            print source
            for version, timestamp in history:
                print "{:>7s}   {:s}".format(
                    version, timestamp.strftime("%Y-%m-%d %H:%M"))
            print
