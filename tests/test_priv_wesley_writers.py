"""#12 should-fix: the Wesley writers take only unflagged wesley-* chunks."""

from __future__ import annotations

import sqlite3
import unittest

from preached.store import SCHEMA, TRIGGERS, replace_chunks, update_chunk_metadata


def chunk(sermon_id: str = "wesley-001", **extra) -> dict:
    return {"chunk_id": f"{sermon_id}-c0000", "sermon_id": sermon_id, "sermon_title": "On Grace", "text": "grace", **extra}


class WesleyWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript(SCHEMA)
        self.connection.executescript(TRIGGERS)

    def test_wesley_chunks_are_written(self) -> None:
        replace_chunks(self.connection, [chunk()])
        update_chunk_metadata(self.connection, [chunk(start_s=1.0)])
        self.assertEqual(self.connection.execute("SELECT sermon_id, start_s FROM chunks").fetchall(), [("wesley-001", 1.0)])

    def test_other_ids_and_flags_are_refused(self) -> None:
        replace_chunks(self.connection, [chunk()])
        for bad in (chunk("church-1"), chunk("spurgeon-191"), chunk(""), {"chunk_id": "x"}, chunk(flag_end_s=1.5),
                    chunk(video_id="church-1")):
            for writer in (replace_chunks, update_chunk_metadata):
                with self.subTest(bad=bad, writer=writer.__name__), self.assertRaises(ValueError):
                    writer(self.connection, [chunk(), bad] if writer is replace_chunks else [bad])
        self.assertEqual(self.connection.execute("SELECT sermon_id FROM chunks").fetchall(), [("wesley-001",)])


if __name__ == "__main__":
    unittest.main()
