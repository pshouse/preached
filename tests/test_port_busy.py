"""A busy port surfaces the real bind error, not an AttributeError from server_close."""

from __future__ import annotations

import errno
import socket
import sys
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from app.server import PreachedServer  # noqa: E402


class PortBusyTests(unittest.TestCase):
    def test_busy_port_raises_address_in_use(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(("127.0.0.1", 0))
            holder.listen(1)
            port = holder.getsockname()[1]
            with self.assertRaises(OSError) as ctx:
                PreachedServer(("127.0.0.1", port), BaseHTTPRequestHandler)
        self.assertNotIsInstance(ctx.exception, AttributeError)
        self.assertEqual(ctx.exception.errno, errno.EADDRINUSE)


if __name__ == "__main__":
    unittest.main()
