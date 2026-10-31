"""Start base and new servers (bm25-only, wesley) and compare raw responses.

    python3 -I scripts/compare_responses.py BASE_TREE NEW_TREE

Each tree gets its own server on an ephemeral port (``--port 0``), with the
same scrubbed environment: no inherited ``PREACHED_*`` variable except
``PREACHED_CACHE`` (default /cache), set explicitly so both open the same
index. Three server pairs:

- default: GET and HEAD on every path, /healthz, two requests on one
  keep-alive connection, and an X-Forwarded-For from an untrusted peer;
- limited (``PREACHED_RATE_LIMIT=2``): search until 429, then rotate XFF;
- capped (``PREACHED_MAX_CLIENT_CONNECTIONS=1``): a held keep-alive
  connection, then the accept-time 503 for a second one.

Date, ``took_ms`` and Content-Length are masked; Content-Length changes only
when ``took_ms`` changes width.
"""
import os
import re
import socket
import subprocess
import sys

TREES = {"base": sys.argv[1], "new": sys.argv[2]}
CACHE = os.environ.get("PREACHED_CACHE", "/cache")
PATHS = ["/api/search?q=christian+perfection&k=5", "/api/search?q=grace&mode=keyword&k=3",
         "/api/search?q=faith&mode=hybrid", "/api/search?q=", "/api/search?q=x&k=999",
         "/api/sermon/wesley-001", "/api/sermon/wesley-040", "/api/sermon/nope", "/api/sermon/..%2f",
         "/api/side?q=love", "/", "/static/app.js", "/missing", "/healthz"]


def start(tree, extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PREACHED_")}
    env["PREACHED_CACHE"] = CACHE
    env.update(extra)
    proc = subprocess.Popen(["uv", "run", "--project", tree, "python", f"{tree}/app/server.py", "--bm25-only",
                             "--port", "0"], cwd=tree, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True)
    for line in proc.stdout:
        if line.startswith("PREACHED_LISTENING"):
            return proc, int(line.strip().rsplit(":", 1)[1])
    proc.terminate()
    raise SystemExit(f"{tree}: server did not start")


def mask(data):
    data = re.sub(rb"Date: [^\r]*", b"Date: X", data)
    data = re.sub(rb'"took_ms": ?[0-9]+', b'"took_ms": 0', data)
    return re.sub(rb"Content-Length: [0-9]+", b"Content-Length: N", data)


def request(path, method="GET", headers=(), close=True):
    lines = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", *headers]
    if close:
        lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def connect(port, source="127.0.0.1"):
    return socket.create_connection(("127.0.0.1", port), timeout=10, source_address=(source, 0))


def read_to_eof(sock):
    data = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return data
        data += chunk


def read_one(sock, head_only=False):
    """One response, framed by Content-Length (no body for HEAD)."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            return data
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    length = 0 if head_only else int(re.search(rb"Content-Length: ([0-9]+)", head).group(1))
    while len(rest) < length:
        chunk = sock.recv(65536)
        if not chunk:
            break
        rest += chunk
    return head + b"\r\n\r\n" + rest[:length]


def once(port, path, method="GET", headers=(), source="127.0.0.1"):
    sock = connect(port, source)
    try:
        sock.sendall(request(path, method, headers))
        return read_to_eof(sock)
    finally:
        sock.close()


def keep_alive(port, first, second):
    sock = connect(port)
    try:
        sock.sendall(request(first, close=False))
        a = read_one(sock)
        sock.sendall(request(second, close=False))
        return a + b"|" + read_one(sock)
    finally:
        sock.close()


def default_cases():
    cases = [(f"GET {p}", lambda port, p=p: once(port, p)) for p in PATHS]
    cases += [(f"HEAD {p}", lambda port, p=p: once(port, p, "HEAD"))
              for p in ("/api/search?q=grace&k=3", "/api/sermon/wesley-001", "/", "/healthz", "/missing")]
    cases.append(("keep-alive search+sermon",
                  lambda port: keep_alive(port, "/api/search?q=grace&k=3", "/api/sermon/wesley-001")))
    cases.append(("keep-alive healthz+page", lambda port: keep_alive(port, "/healthz", "/")))
    cases.append(("XFF from untrusted peer",
                  lambda port: once(port, "/api/search?q=grace&k=3", headers=("X-Forwarded-For: 198.51.100.7",))))
    return cases


def limited_cases():
    cases = []
    for n in range(3):
        cases.append((f"search #{n + 1} (limit 2)", lambda port: once(port, "/api/search?q=grace&k=3")))
    cases.append(("429 with rotated XFF",
                  lambda port: once(port, "/api/search?q=grace&k=3", headers=("X-Forwarded-For: 203.0.113.9",))))
    cases.append(("429 HEAD", lambda port: once(port, "/api/search?q=grace&k=3", "HEAD")))
    return cases


def capped(port):
    held = connect(port, "127.0.0.2")
    try:
        held.sendall(request("/api/sermon/wesley-001", close=False))
        first = read_one(held)
        refused = once(port, "/api/sermon/wesley-001", source="127.0.0.2")
        return first + b"|" + refused
    finally:
        held.close()


PAIRS = [
    ("default", {}, default_cases()),
    ("limited", {"PREACHED_RATE_LIMIT": "2"}, limited_cases()),
    ("capped", {"PREACHED_MAX_CLIENT_CONNECTIONS": "1"}, [("held keep-alive, then over-cap 503", capped)]),
]

same = total = 0
for label, extra, cases in PAIRS:
    procs = {}
    try:
        for name, tree in TREES.items():
            procs[name] = start(tree, extra)
        for title, case in cases:
            a, b = (mask(case(procs[name][1])) for name in TREES)
            statuses = " ".join(m.decode() for m in re.findall(rb"HTTP/1\.[01] ([0-9]{3})", a))
            print(("SAME " if a == b else "DIFF ") + f"[{label}] {statuses} {title} ({len(a)} bytes)")
            same += a == b
            total += 1
    finally:
        for proc, _ in procs.values():
            proc.terminate()
            proc.wait()
print(f"{same}/{total} identical")
