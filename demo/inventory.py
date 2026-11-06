#!/usr/bin/env python3
"""The dependency. Answers "how many of this item are in stock?" instantly. Think: a database or a downstream API."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/healthz":
            body, status = b"ok\n", 200
        elif self.path.startswith("/stock/"):
            body, status = json.dumps({"sku": self.path[len("/stock/"):], "stock": 42}).encode(), 200
        else:
            body, status = b"not found\n", 404
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
