"""Preached: find a preacher's own words. No generated answers."""

import os

# onnxruntime 1.31.1 (observed) starts Microsoft 1DS telemetry at
# `import onnxruntime`: a device ID and event DB under
# $XDG_CACHE_HOME/Microsoft/DeveloperTools. It reads this variable once, at
# import, so it is set here, unconditionally, before any submodule can import
# onnxruntime. Every `import preached.*` runs this file first.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

__version__ = "0.1.0"
