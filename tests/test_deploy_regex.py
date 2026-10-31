"""Pin the backticked ^...$ regexes in docs/DEPLOY.md to lines the app really emits.

Each pattern is fullmatched against a line produced by driving the real code path,
rendered through the format string main() hands to logging.basicConfig (captured
from main(), not retyped). Exception text is excluded: a line is the formatted
message, as the alert sees the first line of a record.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app.server as server  # noqa: E402
import test_obs_gaps  # noqa: E402  (module, not the class: discovery would rerun its tests)

DEPLOY = Path(__file__).resolve().parents[1] / "docs" / "DEPLOY.md"
PATTERN = re.compile(r"`(\^[^`]*\$)`")


def deploy_patterns() -> list[tuple[str, str, str]]:
    """(where, name, regex) for every backticked ^...$ in DEPLOY.md.

    Table rows are named by their first cell (D2b, stamp); prose by line number.
    """
    found = []
    for number, line in enumerate(DEPLOY.read_text().splitlines(), 1):
        for regex in PATTERN.findall(line):
            if line.startswith("|"):
                found.append(("table", line.split("|")[1].strip(), regex))
            else:
                found.append(("prose", f"DEPLOY.md:{number}", regex))
    return found


def real_format() -> str:
    """The format string main() passes to logging.basicConfig, captured by running main()."""
    seen = {}

    class Stop(Exception):
        pass

    def grab(**kwargs):
        seen.update(kwargs)
        raise Stop

    with patch("app.server.os.geteuid", return_value=1000), patch("logging.basicConfig", side_effect=grab):
        try:
            server.main([])
        except Stop:
            pass
    return seen["format"]


class _Collect(logging.Handler):
    def __init__(self, formatter: logging.Formatter) -> None:
        super().__init__(logging.DEBUG)
        self.setFormatter(formatter)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        # formatMessage applies only the format string, so no traceback: the line the alert reads.
        record.message = record.getMessage()
        self.lines.append(self.formatter.formatMessage(record))


class DeployRegexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.formatter = logging.Formatter(real_format())
        self.collect = _Collect(self.formatter)
        root = logging.getLogger()
        root.addHandler(self.collect)
        old = root.level
        root.setLevel(logging.INFO)
        self.addCleanup(root.setLevel, old)
        self.addCleanup(root.removeHandler, self.collect)

    def reload_lines(self, needle: str) -> list[str]:
        fixture = test_obs_gaps.ReloadFallbackLogTests("requests")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.collect.lines.clear()
        with patch("app.server.index_stamp", side_effect=sqlite3.OperationalError("disk I/O error")):
            for _ in range(3):
                fixture.app.search("grace", 5, "dense")
        return [line for line in self.collect.lines if needle in line]

    def side_access_line(self) -> list[str]:
        handler = server.make_handler(server.App(
            connection=None, searcher=None, encode=None, fallback_note=None, model_name=None,
            hosts={"127.0.0.1"}, static_dir=server.STATIC_DIR,
        ))
        fake = object.__new__(handler)  # the real handler class, minus the socket
        fake.client_address = ("203.0.113.9", 5555)
        fake._client_key = "203.0.113.9"
        fake.command = "GET"
        fake.path = "/api/side"
        self.collect.lines.clear()
        fake.log_request(200)
        return list(self.collect.lines)

    def produce(self, name: str) -> list[str]:
        """The real emitted line(s) for a pattern, chosen by its row, never by its regex text."""
        if name == "D2b":  # reload path, real App._refresh_if_stale
            return self.reload_lines("index status unreadable")
        if name == "stamp":  # real App._capture_stamp
            return self.reload_lines("could not read the index stamp")
        if name == "DEPLOY.md:822":  # access log, real handler.log_request
            return self.side_access_line()
        self.fail(f"no producer for DEPLOY.md pattern {name}: add one, do not skip it")

    def test_the_parser_finds_patterns(self) -> None:
        found = deploy_patterns()
        self.assertGreaterEqual(len(found), 3, f"parser matched {len(found)} patterns in {DEPLOY}")
        tables = {name for where, name, _ in found if where == "table"}
        self.assertTrue({"D2b", "stamp"} <= tables, f"table rows found: {sorted(tables)}")

    def test_every_pattern_fullmatches_a_real_emitted_line(self) -> None:
        found = deploy_patterns()
        self.assertTrue(found, "no ^...$ patterns found in DEPLOY.md")
        for where, name, regex in found:
            with self.subTest(where=where, name=name, regex=regex):
                lines = self.produce(name)
                self.assertTrue(lines, f"{name}: the code path emitted no line")
                print(f"checked {where} {name}: {regex} <- {lines[0]!r}", file=sys.stderr)
                self.assertTrue(
                    all(re.fullmatch(regex, line) for line in lines),
                    f"{name}: {regex!r} does not fullmatch real line(s) {lines!r}",
                )


if __name__ == "__main__":
    unittest.main()
