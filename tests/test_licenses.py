"""wesley.provenance.json must match what wesley.jsonl says."""

from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent.parent / "ingest" / "manifest"


class WesleyProvenanceTests(unittest.TestCase):
    def test_tracks_and_licenses_match_the_manifest(self) -> None:
        rows = [json.loads(line) for line in (MANIFEST / "wesley.jsonl").read_text().splitlines() if line.strip()]
        tracks = Counter(r["ia_identifier"] for r in rows)
        licenses: dict[str, set] = {}
        for r in rows:
            licenses.setdefault(r["ia_identifier"], set()).add(r["license_url"])
        items = json.loads((MANIFEST / "wesley.provenance.json").read_text())["ia_items"]
        self.assertEqual({i["ia_identifier"] for i in items}, set(tracks))
        for item in items:
            ident = item["ia_identifier"]
            self.assertEqual(item["tracks"], tracks[ident], ident)
            self.assertEqual({item["licenseurl"]}, licenses[ident], ident)
