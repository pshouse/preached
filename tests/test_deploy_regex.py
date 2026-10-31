"""Pin the backticked ^...$ regexes in docs/DEPLOY.md to lines the app really emits.

Each pattern is fullmatched against a line produced by driving the real code path,
rendered through the formatter main() actually installs (the root handler after
logging setup, not a retyped format string). Exception text is excluded: the
alert reads the first line of the record. asctime is filled by
logging.Formatter.format when the format uses it.

Table rows are keyed by the alert id in the first cell. Prose patterns are
keyed by an explicit ``<!-- regex: name -->`` marker beside the pattern, never
by a line number. An unknown anchor fails with "no producer".
"""

from __future__ import annotations

import inspect
import logging
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app.server as server  # noqa: E402
import test_obs_gaps  # noqa: E402  (module, not the class: discovery would rerun its tests)

DEPLOY = Path(__file__).resolve().parents[1] / "docs" / "DEPLOY.md"
# The formatter main() installs. Alerts anchor on this, including the defaults
# basicConfig fills in when style and datefmt are omitted.
EXPECT_FORMAT = "%(levelname)s %(message)s"
EXPECT_STYLE = "%"
EXPECT_DATEFMT = None
# Exact set. A wrapped or unanchored pattern that the parser used to skip
# changes this set or adds a parse problem, and the test fails.
EXPECTED_PATTERNS = {"D2b", "stamp", "side-access"}
# Infra Ops keeps the yaml outside this repo. Optional check when it is mounted.
INFRA_ALERTS = Path("/workspace/infra-ops/preached/alerts/church-alerts.yaml")
INFRA_RULES = {
    "D2b": "deploy-index-status-unreadable-bm25",
    "stamp": "deploy-index-stamp-unreadable",
    "side-access": "church-paused-stuck",
}
_MARKER = re.compile(r"<!--\s*regex:\s*([A-Za-z0-9][A-Za-z0-9-]*)\s*-->")
_BACKTICK = re.compile(r"`([^`]*)`", re.DOTALL)
_STYLES = {
    logging.PercentStyle: "%",
    logging.StrFormatStyle: "{",
    logging.StringTemplateStyle: "$",
}
# Names main() can reach after (or, if reordered, before) logging setup.
# Each is stubbed so a reorder cannot open the index, load a model, bind a
# port, or touch the real cache.
_STARTUP = (
    "resolve_flagged_audio",
    "default_config",
    "required_config",
    "file_identity",
    "bundle_problem",
    "is_bundle",
    "onnx_dir_problem",
    "prepare_church",
    "open_readonly",
    "check_servable",
    "church_path_for",
    "open_church",
    "build_app",
    "make_server",
    "serve_until_stopped",
    "serve_forever",
    "load_search",
)


class _StopAfterLogging(Exception):
    """basicConfig ran. Nothing after it in main() may run."""


def _collapse(token: str) -> str:
    """Join a backtick that markdown wrapped across lines into one pattern."""
    return re.sub(r"\s+", " ", token).strip()


def _scan_tokens(text: str) -> tuple[list[str], list[str]]:
    """Backtick tokens that start with ^, plus a problem for each one with no $."""
    patterns = []
    problems = []
    for raw in _BACKTICK.findall(text):
        token = _collapse(raw)
        if not token.startswith("^"):
            continue
        if token.endswith("$"):
            patterns.append(token)
        else:
            problems.append(f"backticked pattern starts with ^ but has no $: {token!r}")
    return patterns, problems


def parse_deploy(text: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """(where, name, regex) for every anchored ^...$ , and loud parse problems.

    Paragraph lines are joined before matching, so a wrapped backtick is one
    token. Table rows stay one line and are named by the alert id (first cell).
    Prose is named by ``<!-- regex: name -->`` in that paragraph.
    """
    found: list[tuple[str, str, str]] = []
    problems: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        lines = [line for line in para.splitlines() if line.strip()]
        if not lines:
            continue
        if all(line.lstrip().startswith("|") for line in lines):
            for line in lines:
                patterns, token_problems = _scan_tokens(line)
                problems.extend(token_problems)
                if not patterns:
                    continue
                alert = line.split("|")[1].strip() if "|" in line else ""
                if not alert or set(alert) <= {"-", ":"}:
                    problems.append(f"table ^...$ has no alert id: {patterns!r}")
                    continue
                for regex in patterns:
                    found.append(("table", alert, regex))
            continue
        patterns, token_problems = _scan_tokens(para)
        problems.extend(token_problems)
        markers = _MARKER.findall(para)
        if patterns and len(markers) != len(patterns):
            if not markers:
                for regex in patterns:
                    problems.append(
                        "no producer for DEPLOY.md pattern "
                        f"{regex!r}: prose ^...$ has no <!-- regex: name --> anchor; "
                        "add one, do not skip it"
                    )
            else:
                problems.append(
                    "no producer for DEPLOY.md pattern: anchors "
                    f"{markers} do not line up with {patterns!r}"
                )
        else:
            for name, regex in zip(markers, patterns):
                found.append(("prose", name, regex))
        if markers and not patterns and not token_problems:
            for name in markers:
                problems.append(f"regex anchor {name!r} has no ^...$ pattern beside it")
    return found, problems


def deploy_patterns() -> tuple[list[tuple[str, str, str]], list[str]]:
    return parse_deploy(DEPLOY.read_text(encoding="utf-8"))


def _under_temp(path: Path) -> None:
    root = Path(tempfile.gettempdir()).resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise AssertionError(f"{resolved} is not under {root}")


def _not_first(*_args, **_kwargs):
    raise RuntimeError("basicConfig not reached first")


def _installed_formatter(kwargs: dict) -> logging.Formatter:
    """The formatter on the one root handler basicConfig left behind.

    A handler or formatter installed some other way (S11: a StreamHandler
    added before basicConfig) does not match these kwargs and fails here.
    """
    root = logging.getLogger()
    handlers = list(root.handlers)
    if len(handlers) != 1:
        raise AssertionError(
            f"main configured {len(handlers)} root handlers; expected exactly one StreamHandler"
        )
    handler = handlers[0]
    if type(handler) is not logging.StreamHandler:
        raise AssertionError(
            f"root handler is {type(handler).__name__}, expected StreamHandler"
        )
    formatter = handler.formatter
    if type(formatter) is not logging.Formatter:
        raise AssertionError(
            f"root formatter is {type(formatter).__name__}, expected Formatter"
        )
    style = _STYLES.get(type(formatter._style))
    got_format = formatter._fmt
    got_datefmt = formatter.datefmt
    want_format = kwargs.get("format", EXPECT_FORMAT)
    want_style = kwargs.get("style", EXPECT_STYLE)
    want_datefmt = kwargs.get("datefmt", EXPECT_DATEFMT)
    problems = []
    if got_format != want_format:
        problems.append(f"format {got_format!r} != basicConfig format {want_format!r}")
    if style != want_style:
        problems.append(f"style {style!r} != basicConfig style {want_style!r}")
    if got_datefmt != want_datefmt:
        problems.append(f"datefmt {got_datefmt!r} != basicConfig datefmt {want_datefmt!r}")
    if want_format != EXPECT_FORMAT:
        problems.append(f"basicConfig format {want_format!r} != {EXPECT_FORMAT!r}")
    if want_style != EXPECT_STYLE:
        problems.append(f"basicConfig style {want_style!r} != {EXPECT_STYLE!r}")
    if want_datefmt != EXPECT_DATEFMT:
        problems.append(f"basicConfig datefmt {want_datefmt!r} != {EXPECT_DATEFMT!r}")
    if kwargs.get("level") != logging.INFO:
        problems.append(f"basicConfig level {kwargs.get('level')!r} != INFO")
    extra = sorted(set(kwargs) - {"level", "format", "style", "datefmt"})
    if extra:
        problems.append(f"basicConfig kwargs configure something else: {extra}")
    if problems:
        raise AssertionError("logging setup mismatch: " + "; ".join(problems))
    return formatter


def capture_root_formatter(entry=None) -> logging.Formatter:
    """Run main only through logging setup and return the installed formatter.

    basicConfig is the real one, so the root handler is the one a process
    would have. The call then stops. Every later startup function raises
    ``basicConfig not reached first`` if main() reaches it anyway, which is
    what a reorder does. CUDA_VISIBLE_DEVICES is set inside patch.dict and
    cannot leak. Cache, model and port env vars point at a temp dir for this
    call; the stubs never use them.
    """
    entry = server.main if entry is None else entry
    cuda_before = os.environ.get("CUDA_VISIBLE_DEVICES")
    state: dict = {}
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    for handler in saved_handlers:
        root.removeHandler(handler)
    # A fresh root, as when main() is the process entry point. Leaving a
    # handler in place would make basicConfig a no-op and hide S11.
    root.setLevel(logging.NOTSET)

    def run() -> logging.Formatter:
        try:
            entry([])
        except _StopAfterLogging:
            if "kwargs" not in state:
                raise AssertionError("basicConfig not reached first") from None
            return _installed_formatter(state["kwargs"])
        except RuntimeError as exc:
            if exc.args == ("basicConfig not reached first",):
                raise AssertionError("basicConfig not reached first") from exc
            raise
        else:
            raise AssertionError("basicConfig not reached first")

    try:
        with tempfile.TemporaryDirectory(prefix="preached-regex-pin-") as tmp:
            _under_temp(Path(tmp))
            offline = {
                "HF_HUB_OFFLINE": "1",
                "HF_HOME": tmp,
                "PREACHED_CACHE": tmp,
                "PREACHED_ONNX_DIR": tmp,
                "TMPDIR": tmp,
                "TRANSFORMERS_OFFLINE": "1",
                "HF_DATASETS_OFFLINE": "1",
            }
            with patch.dict(os.environ, offline), patch("app.server.os.geteuid", return_value=1000):
                patches = [patch.object(server, name, side_effect=_not_first) for name in _STARTUP]
                patches.append(patch.object(server.argparse.ArgumentParser, "parse_args", _not_first))
                patches.append(patch.object(server.App, "__init__", _not_first))
                # Wrap basicConfig after the startup stubs. Calling the saved
                # function (not the patched name) does the real configuration.
                real_basic = logging.basicConfig

                def wrapped_real(**kwargs):
                    state["kwargs"] = dict(kwargs)
                    real_basic(**dict(kwargs))
                    raise _StopAfterLogging

                patches.append(patch("logging.basicConfig", side_effect=wrapped_real))
                for item in patches:
                    item.start()
                try:
                    return run()
                finally:
                    for item in reversed(patches):
                        item.stop()
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)
        if os.environ.get("CUDA_VISIBLE_DEVICES") != cuda_before:
            raise AssertionError("CUDA_VISIBLE_DEVICES leaked out of logging capture")


def _main_with_logging_moved_below_open():
    """A copy of main() whose basicConfig call sits after open_readonly.

    The returned function reads server globals at call time, so the startup
    stubs in capture_root_formatter still apply.
    """
    source = inspect.getsource(server.main)
    lines = source.splitlines(keepends=True)
    basic = [i for i, line in enumerate(lines) if "logging.basicConfig(" in line]
    opens = [i for i, line in enumerate(lines) if line.lstrip().startswith("connection = open_readonly(")]
    if len(basic) != 1 or len(opens) != 1 or basic[0] > opens[0]:
        raise AssertionError("main() no longer configures logging before opening the index")
    line = lines.pop(basic[0])
    open_at = opens[0] - 1
    # Keep the moved call inside the try that opens the index. Its original
    # indent would close that try and the mutant would not compile.
    indent = lines[open_at][: len(lines[open_at]) - len(lines[open_at].lstrip())]
    lines.insert(open_at + 1, indent + line.lstrip())
    saved = server.main
    try:
        exec("".join(lines), server.__dict__)
        return server.main
    finally:
        server.main = saved


class _Collect(logging.Handler):
    def __init__(self, formatter: logging.Formatter) -> None:
        super().__init__(logging.DEBUG)
        self.setFormatter(formatter)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        # The real Formatter.format fills asctime. The alert matches the first
        # line only; a traceback is on the following lines.
        rendered = logging.Formatter.format(self.formatter, record)
        self.lines.append(rendered.splitlines()[0])


class DeployRegexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.formatter = capture_root_formatter()
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
        # _client_key is set, so log_request's _log_key() returns it and does
        # not read X-Forwarded-For. That header path is not what this pins.
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
        """The real emitted line(s) for a pattern, chosen by its anchor, never by its regex text."""
        if name == "D2b":  # reload path, real App._refresh_if_stale
            return self.reload_lines("index status unreadable")
        if name == "stamp":  # real App._capture_stamp
            return self.reload_lines("could not read the index stamp")
        if name == "side-access":  # access log, real handler.log_request
            return self.side_access_line()
        self.fail(f"no producer for DEPLOY.md pattern {name}: add one, do not skip it")

    def _patterns(self) -> list[tuple[str, str, str]]:
        found, problems = deploy_patterns()
        if problems:
            self.fail("DEPLOY.md regex parse failed:\n" + "\n".join(problems))
        return found

    def test_the_parser_finds_the_pinned_patterns(self) -> None:
        found = self._patterns()
        names = [name for _where, name, _regex in found]
        self.assertEqual(sorted(names), sorted(EXPECTED_PATTERNS), names)
        self.assertEqual(len(names), len(set(names)), f"duplicate pattern names: {names}")

    def test_a_leading_blank_line_does_not_rename_patterns(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        self.assertEqual(parse_deploy(text), parse_deploy("\n" + text))

    def test_a_prose_pattern_without_its_anchor_fails_loudly(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8").replace(" <!-- regex: side-access -->", "")
        _found, problems = parse_deploy(text)
        self.assertTrue(problems, "removing the anchor was skipped")
        self.assertTrue(any("no producer" in problem for problem in problems), problems)

    def test_a_wrapped_backtick_is_one_pattern(self) -> None:
        text = "See `^ERROR index status\nunreadable after reload; serving BM25 only$` <!-- regex: wrapped -->\n"
        found, problems = parse_deploy(text)
        self.assertEqual(problems, [])
        self.assertEqual(
            found,
            [("prose", "wrapped", "^ERROR index status unreadable after reload; serving BM25 only$")],
        )

    def test_a_caret_token_without_a_dollar_is_flagged(self) -> None:
        text = "See `^INFO no dollar here` and `^INFO anchored$` <!-- regex: kept -->\n"
        _found, problems = parse_deploy(text)
        self.assertTrue(any("no $" in problem for problem in problems), problems)

    def test_every_pattern_fullmatches_a_real_emitted_line(self) -> None:
        found = self._patterns()
        self.assertTrue(found, "no ^...$ patterns found in DEPLOY.md")
        # produce() runs before the set check so an unknown anchor fails with
        # "no producer" rather than a set diff that hides that sentence.
        for where, name, regex in found:
            with self.subTest(where=where, name=name, regex=regex):
                lines = self.produce(name)
                self.assertTrue(lines, f"{name}: the code path emitted no line")
                print(f"checked {where} {name}: {regex} <- {lines[0]!r}", file=sys.stderr)
                self.assertTrue(
                    all(re.fullmatch(regex, line) for line in lines),
                    f"{name}: {regex!r} does not fullmatch real line(s) {lines!r}",
                )
        self.assertEqual({name for _where, name, _regex in found}, EXPECTED_PATTERNS)

    def test_rendering_fills_asctime_from_formatter_format(self) -> None:
        formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y")
        collect = _Collect(formatter)
        record = logging.LogRecord("root", logging.INFO, __file__, 1, "hello", (), None)
        collect.emit(record)
        self.assertEqual(len(collect.lines), 1)
        self.assertRegex(collect.lines[0], r"^\d{4} hello$")

    def test_a_handler_added_before_basicconfig_does_not_match(self) -> None:
        """S11: basicConfig's format= is right, but the installed formatter is not."""
        real = server.main

        def mutant(argv=None):
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
            logging.getLogger().addHandler(handler)
            return real(argv)

        with self.assertRaises(AssertionError) as caught:
            capture_root_formatter(mutant)
        self.assertIn("logging setup mismatch", str(caught.exception))
        self.assertIn("%(levelname)s: %(message)s", str(caught.exception))

    def test_a_reordered_main_fails_before_startup(self) -> None:
        real_open = server.open_readonly
        calls = []

        def spy(*args, **kwargs):
            calls.append(args)
            return real_open(*args, **kwargs)

        server.open_readonly = spy
        try:
            mutant = _main_with_logging_moved_below_open()
            with self.assertRaises(AssertionError) as caught:
                capture_root_formatter(mutant)
            self.assertEqual(str(caught.exception), "basicConfig not reached first")
            self.assertEqual(calls, [])
        finally:
            server.open_readonly = real_open

    def test_infra_yaml_matches_when_the_file_is_present(self) -> None:
        path = Path(os.environ["PREACHED_INFRA_ALERTS"]) if os.environ.get("PREACHED_INFRA_ALERTS") else INFRA_ALERTS
        if not path.is_file():
            self.skipTest(f"infra alerts yaml absent ({path})")
        import yaml  # the ops file is YAML; not a project dependency

        found = self._patterns()
        by_name = {name: regex for _where, name, regex in found}
        rules = list(_yaml_rules(yaml.safe_load(path.read_text(encoding="utf-8"))))
        for name, rule_id in INFRA_RULES.items():
            regex = by_name[name]
            matched = [
                rule for rule in rules
                if rule_id in _yaml_strings(rule)
                and regex in _pattern_strings(rule)
            ]
            self.assertTrue(
                matched,
                f"{name}: DEPLOY regex {regex!r} != pattern/evidence_pattern on infra rule {rule_id}",
            )


def _yaml_rules(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _yaml_rules(value)
    elif isinstance(node, list):
        for item in node:
            yield from _yaml_rules(item)


def _yaml_strings(node) -> set[str]:
    found = set()
    if isinstance(node, str):
        found.add(node)
    elif isinstance(node, dict):
        for value in node.values():
            found |= _yaml_strings(value)
    elif isinstance(node, list):
        for item in node:
            found |= _yaml_strings(item)
    return found


def _pattern_strings(rule: dict) -> set[str]:
    found = set()
    if not isinstance(rule, dict):
        return found
    for key in ("pattern", "evidence_pattern"):
        value = rule.get(key)
        if isinstance(value, str):
            found.add(value)
    return found


if __name__ == "__main__":
    unittest.main()
