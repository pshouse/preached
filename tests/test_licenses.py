"""wesley.provenance.json must match what wesley.jsonl says."""

from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent.parent / "ingest" / "manifest"

# provenance ia_items key -> wesley.jsonl row key
ITEM_FIELDS = {
    "ia_url": "ia_url",
    "librivox_url": "librivox_url",
    "work": "work",
    "series": "series",
    "licenseurl": "license_url",
    "audio_format": "audio_format",
}


def load() -> tuple[list[dict], dict]:
    rows = [json.loads(line) for line in (MANIFEST / "wesley.jsonl").read_text().splitlines() if line.strip()]
    return rows, json.loads((MANIFEST / "wesley.provenance.json").read_text())


def check(rows: list[dict], provenance: dict) -> None:
    """Raise AssertionError if any generated field of provenance disagrees with rows."""
    tracks = Counter(r["ia_identifier"] for r in rows)
    items = provenance["ia_items"]
    if len(items) != len({i["ia_identifier"] for i in items}):
        raise AssertionError("duplicate ia_items entry")
    if {i["ia_identifier"] for i in items} != set(tracks):
        raise AssertionError("identifiers differ")
    expected_keys = {"ia_identifier", "tracks", *ITEM_FIELDS}
    for item in items:
        if set(item) != expected_keys:
            raise AssertionError(f"{item['ia_identifier']}: keys {sorted(set(item) ^ expected_keys)}")
        ident = item["ia_identifier"]
        mine = [r for r in rows if r["ia_identifier"] == ident]
        if item["tracks"] != tracks[ident]:
            raise AssertionError(f"{ident}: tracks")
        for key, row_key in ITEM_FIELDS.items():
            if {r[row_key] for r in mine} != {item[key]}:
                raise AssertionError(f"{ident}: {key}")
    if {r["text_source_url"] for r in rows} != {provenance["text_source_url"]}:
        raise AssertionError("text_source_url")


class WesleyProvenanceTests(unittest.TestCase):
    def test_every_generated_field_matches_the_manifest(self) -> None:
        rows, provenance = load()
        check(rows, provenance)

    def test_guard_catches_each_field(self) -> None:
        rows, provenance = load()
        for key in ITEM_FIELDS:
            changed = json.loads(json.dumps(provenance))
            changed["ia_items"][0][key] += "x"
            with self.assertRaises(AssertionError, msg=key):
                check(rows, changed)
        changed = json.loads(json.dumps(provenance))
        changed["text_source_url"] += "x"
        with self.assertRaises(AssertionError):
            check(rows, changed)
        changed = json.loads(json.dumps(provenance))
        changed["ia_items"][0]["tracks"] += 1
        with self.assertRaises(AssertionError):
            check(rows, changed)

    def test_guard_catches_a_duplicated_item(self) -> None:
        rows, provenance = load()
        changed = json.loads(json.dumps(provenance))
        changed["ia_items"].append(dict(changed["ia_items"][0]))
        with self.assertRaisesRegex(AssertionError, "duplicate"):
            check(rows, changed)

    def test_guard_catches_an_extra_key_in_an_item(self) -> None:
        rows, provenance = load()
        changed = json.loads(json.dumps(provenance))
        changed["ia_items"][0]["extra"] = "x"
        with self.assertRaisesRegex(AssertionError, "keys"):
            check(rows, changed)

    def test_note_does_not_claim_the_license_note_is_generated(self) -> None:
        _, provenance = load()
        self.assertIn("hand-written", provenance["note"])
