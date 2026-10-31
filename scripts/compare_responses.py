"""Start base and new servers (bm25-only, wesley) and compare raw responses."""
import re, socket, subprocess, sys, time, os
trees = {"base": sys.argv[1], "new": sys.argv[2]}
ports = {"base": 18731, "new": 18732}
paths = ["/api/search?q=christian+perfection&k=5", "/api/search?q=grace&mode=keyword&k=3",
         "/api/search?q=faith&mode=hybrid", "/api/search?q=", "/api/search?q=x&k=999",
         "/api/sermon/wesley-001", "/api/sermon/wesley-040", "/api/sermon/nope", "/api/sermon/..%2f",
         "/api/side?q=love", "/", "/static/app.js", "/missing"]
procs = {}
for name, tree in trees.items():
    procs[name] = subprocess.Popen(["uv", "run", "--project", tree, "python", f"{tree}/app/server.py", "--bm25-only",
        "--port", str(ports[name])], cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
for name, proc in procs.items():
    for line in proc.stdout:
        if line.startswith("PREACHED_LISTENING"):
            break
def raw(port, path):
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
    data = b""
    while True:
        c = s.recv(65536)
        if not c: break
        data += c
    s.close()
    data = re.sub(rb"Date: [^\r]*", b"Date: X", data)
    data = re.sub(rb'"took_ms": ?[0-9]+', b'"took_ms": 0', data)
    data = re.sub(rb"Content-Length: [0-9]+", b"Content-Length: N", data)
    return data
same = 0
try:
    for path in paths:
        a, b = raw(ports["base"], path), raw(ports["new"], path)
        status = a.split(b"\r\n", 1)[0].decode()
        print(("SAME " if a == b else "DIFF ") + status + " " + path + f" ({len(a)} bytes)")
        same += a == b
finally:
    for p in procs.values(): p.terminate()
print(f"{same}/{len(paths)} identical")
