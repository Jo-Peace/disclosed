"""Serve the static site locally:  python -m disclosed.serve [--port 8000]   (site/ is plain static files; any static host works)"""
import argparse, functools, http.server, socketserver
from . import config
ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8000); ap.add_argument("--host", default="127.0.0.1"); a = ap.parse_args()
H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(config.ROOT / "site"))
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer((a.host, a.port), H) as s:
    print(f"serving site/ at http://{a.host}:{a.port}/"); s.serve_forever()
