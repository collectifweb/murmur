"""Relais M8 : sert les scripts au Mac (GET) et reçoit ses journaux (PUT).

Rien d'autre. Tourne sur le LAN, le temps de la session M8.
"""

import http.server
import pathlib
import socketserver

BASE = pathlib.Path(__file__).resolve().parent
SERVE = BASE / "serve"
LOGS = BASE / "logs"
LOGS.mkdir(exist_ok=True)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SERVE), **kw)

    def do_PUT(self):
        name = pathlib.PurePosixPath(self.path).name or "sans-nom.log"
        if not name.endswith((".log", ".txt", ".json")):
            self.send_error(400, "extension refusee")
            return
        length = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(length) if length else b""
        (LOGS / name).write_bytes(data)
        self.send_response(201)
        self.end_headers()
        self.wfile.write(b"ok\n")

    do_POST = do_PUT


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", 8010), Handler) as httpd:
        print("relais M8 sur 0.0.0.0:8010", flush=True)
        httpd.serve_forever()
