"""Tests for wealth/service.py's _connect() - the AES-256 (SQLCipher) encryption-at-rest layer
added 2026-09-28 (see GAP_PLAN.md's "encrypt private data and backups"). data/wealth.sqlite3 was
plaintext before this."""

import os
import sqlite3 as stdlib_sqlite3
import tempfile
import unittest

from wealth.service import _connect, _HEX_KEY

VALID_KEY = "a1" * 32  # 64 hex chars = a real 256-bit key shape


class HexKeyValidationTests(unittest.TestCase):
    def test_a_valid_64_char_hex_key_matches(self):
        self.assertTrue(_HEX_KEY.match(VALID_KEY))

    def test_a_short_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "db.sqlite3")
            with self.assertRaises(ValueError):
                _connect(path, "abc123")

    def test_a_non_hex_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "db.sqlite3")
            with self.assertRaises(ValueError):
                _connect(path, "z" * 64)  # 'z' isn't hex

    def test_an_empty_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "db.sqlite3")
            with self.assertRaises(ValueError):
                _connect(path, "")


class EncryptedRoundTripTests(unittest.TestCase):
    def test_data_written_with_the_key_reads_back_with_the_same_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "db.sqlite3")
            with _connect(path, VALID_KEY) as db:
                db.execute("CREATE TABLE t(x)")
                db.execute("INSERT INTO t VALUES (42)")
            with _connect(path, VALID_KEY) as db:
                self.assertEqual(db.execute("SELECT * FROM t").fetchall(), [(42,)])

    def test_the_wrong_key_cannot_read_the_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "db.sqlite3")
            with _connect(path, VALID_KEY) as db:
                db.execute("CREATE TABLE t(x)")
                db.execute("INSERT INTO t VALUES (42)")
            wrong_key = "b2" * 32
            with self.assertRaises(Exception):
                with _connect(path, wrong_key) as db:
                    db.execute("SELECT * FROM t").fetchall()

    def test_the_file_on_disk_is_not_readable_as_plain_sqlite(self):
        # The real proof this isn't just "trust the library": open the same file with the
        # stdlib's own unmodified sqlite3 module and confirm it can't read it as a normal
        # database - a plaintext SQLite file always starts with the literal header
        # "SQLite format 3\x00"; an encrypted SQLCipher file does not.
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "db.sqlite3")
            with _connect(path, VALID_KEY) as db:
                db.execute("CREATE TABLE accounts(balance_cents INTEGER)")
                db.execute("INSERT INTO accounts VALUES (123456)")
            with open(path, "rb") as raw:
                header = raw.read(16)
            self.assertNotEqual(header, b"SQLite format 3\x00")
            plain = stdlib_sqlite3.connect(path)
            with self.assertRaises(stdlib_sqlite3.DatabaseError):
                plain.execute("SELECT * FROM accounts").fetchall()

    def test_raw_bytes_never_contain_the_plaintext_value_written(self):
        # A second, independent confirmation: grep the raw file bytes for a distinctive
        # plaintext value that was written - it must not appear anywhere in the ciphertext.
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "db.sqlite3")
            marker = b"UNENCRYPTED_CANARY_VALUE_should_never_appear_on_disk"
            with _connect(path, VALID_KEY) as db:
                db.execute("CREATE TABLE t(x TEXT)")
                db.execute("INSERT INTO t VALUES (?)", (marker.decode(),))
            with open(path, "rb") as raw:
                contents = raw.read()
            self.assertNotIn(marker, contents)


if __name__ == "__main__":
    unittest.main()
