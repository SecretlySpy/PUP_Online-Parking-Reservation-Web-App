"""Project package init.

Register PyMySQL as the MySQLdb driver so the ``django.db.backends.mysql``
engine works with the pure-Python ``pymysql`` package (no C build toolchain
required on Windows / Python 3.14). This is a no-op when SQLite is used.
"""

import pymysql

pymysql.install_as_MySQLdb()
