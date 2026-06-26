#!/usr/bin/env python3
"""
Simple HTTP proxy server that serves the production frontend build
and proxies /api requests to the Flask backend.

Usage:
  python proxy-server.py [--port PORT]

Default port: 5180
Backend: http://localhost:5000
"""

import argparse
import http.server
import json
import mimetypes
import os
import pathlib
import urllib.request
import urllib.error
import socketserver

FRONTEND_DIR = pathlib.Path(__file__).parent / "dist"
BACKEND_URL = "http://localhost:5000"


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    """Serves static files and proxies /api requests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _proxy_request(self, method: str):
        """Proxy a request to the Flask backend."""
        path = self.path
        target_url = f"{BACKEND_URL}{path}"

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Build the upstream request
        req = urllib.request.Request(
            target_url,
            data=body,
            method=method,
            headers={
                k: v
                for k, v in self.headers.items()
                if k.lower()
                not in (
                    "host",
                    "connection",
                    "transfer-encoding",
                    "accept-encoding",
                )
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as upstream:
                response_body = upstream.read()
                self.send_response(upstream.status)
                # Copy response headers
                for key, value in upstream.headers.items():
                    if key.lower() not in (
                        "transfer-encoding",
                        "content-encoding",
                        "content-length",
                        "connection",
                    ):
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)
        except urllib.error.HTTPError as e:
            response_body = e.read()
            self.send_response(e.code)
            for key, value in e.headers.items():
                if key.lower() not in (
                    "transfer-encoding",
                    "content-encoding",
                    "content-length",
                    "connection",
                ):
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        except urllib.error.URLError as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "error": {
                            "message": f"Backend unreachable: {e.reason}",
                            "status_code": 502,
                        },
                        "success": False,
                    }
                ).encode()
            )

    def _serve_static_or_spa(self):
        """Serve static file or fall back to index.html for SPA routing."""
        # Strip query strings
        path = urllib.parse.urlparse(self.path).path

        # Try exact file match
        file_path = FRONTEND_DIR / path.lstrip("/")
        if file_path.exists() and file_path.is_file():
            self._serve_file(file_path)
            return

        # If path has a dot extension and file doesn't exist, return 404
        if "." in path.split("/")[-1]:
            self.send_error(404, "Not found")
            return

        # SPA fallback: serve index.html
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            self._serve_file(index_path)
        else:
            self.send_error(404, "Not found (no index.html)")

    def _serve_file(self, file_path: pathlib.Path):
        """Serve a static file with the correct content type."""
        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(500, "Internal server error")

    def do_GET(self):
        if self.path.startswith("/api") or self.path.startswith("/auth"):
            self._proxy_request("GET")
        else:
            self._serve_static_or_spa()

    def do_POST(self):
        if self.path.startswith("/api") or self.path.startswith("/auth"):
            self._proxy_request("POST")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_PUT(self):
        if self.path.startswith("/api") or self.path.startswith("/auth"):
            self._proxy_request("PUT")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        if self.path.startswith("/api") or self.path.startswith("/auth"):
            self._proxy_request("DELETE")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_PATCH(self):
        if self.path.startswith("/api") or self.path.startswith("/auth"):
            self._proxy_request("PATCH")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS"
        )
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()


def main():
    parser = argparse.ArgumentParser(description="Frontend proxy server")
    parser.add_argument("--port", type=int, default=5180, help="Port to serve on")
    args = parser.parse_args()

    if not FRONTEND_DIR.exists():
        print(
            f"ERROR: Frontend build directory not found at {FRONTEND_DIR}.\n"
            f"Run `cd {FRONTEND_DIR.parent} && npm run build` first."
        )
        exit(1)

    if not (FRONTEND_DIR / "index.html").exists():
        print(
            f"ERROR: No index.html found in {FRONTEND_DIR}.\n"
            f"Run `cd {FRONTEND_DIR.parent} && npm run build` first."
        )
        exit(1)

    server = socketserver.TCPServer(("0.0.0.0", args.port), ProxyHandler)
    print(
        f"🚀 Frontend proxy server running at http://localhost:{args.port}/\n"
        f"   Serving static files from: {FRONTEND_DIR}\n"
        f"   Proxying /api/* and /auth/* to: {BACKEND_URL}\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()