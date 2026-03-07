import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

import psycopg

from db_conn import resolve_database_conninfo

PORT = int(os.environ.get("PORT", 8080))


class DashboardHandler(SimpleHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fetch_ingest_items(self):
        conninfo, reason = resolve_database_conninfo()
        if not conninfo:
            return [], f"database_unavailable:{reason}"

        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT title, url, source_type, LEFT(content, 255), created_at
                    FROM sources
                    ORDER BY created_at DESC, id DESC
                    """
                )
                return [
                    {
                        "title": row[0] or "Untitled",
                        "url": row[1] or "",
                        "source_type": row[2],
                        "description": row[3] or "",
                        "created_at": row[4].isoformat() if row[4] else None,
                    }
                    for row in cur.fetchall()
                ], None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/ingest":
            try:
                items, warning = self._fetch_ingest_items()
            except Exception as exc:
                self._send_json({"items": [], "warning": f"failed_to_fetch_ingest:{exc}"}, status=500)
                return

            self._send_json({"items": items, "warning": warning})
            return

        if self.path == "/":
            self.path = "/dashboard.html"
        return super().do_GET()


if __name__ == "__main__":
    httpd = HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    print(f"Serving dashboard at http://0.0.0.0:{PORT}/")
    httpd.serve_forever()
