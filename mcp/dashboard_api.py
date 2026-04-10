"""Simple REST API wrapper around the SQLite database for the local dashboard.

Runs alongside the MCP server on port 8001.
"""

import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
import db


class DashboardAPI(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # Serve dashboard.html
        if path == "/dashboard.html" or path == "/":
            dashboard_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard.html")
            if os.path.exists(dashboard_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(dashboard_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            self.send_response(404)
            self.end_headers()
            return

        # CORS headers
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            if path == "/api/latest":
                data = db.fetch_all("""
                    SELECT mt.name, mt.display_name, mt.unit, mt.category, mt.viz_type,
                           mr.value, mr.timestamp, mr.notes,
                           sr.min_value AS safe_min, sr.max_value AS safe_max
                    FROM metric_readings mr
                    JOIN metric_types mt ON mr.metric_type_id = mt.id
                    LEFT JOIN safe_ranges sr ON sr.metric_name = mt.name
                    WHERE mr.id IN (
                        SELECT mr2.id FROM metric_readings mr2
                        GROUP BY mr2.metric_type_id
                        HAVING mr2.timestamp = MAX(mr2.timestamp)
                    )
                    ORDER BY mt.category, mt.name
                """)
            elif path == "/api/metrics":
                data = db.fetch_all(
                    "SELECT name, display_name, unit, category, viz_type FROM metric_types ORDER BY category, name"
                )
            elif path == "/api/readings":
                name = params.get("name", [None])[0]
                if not name:
                    data = {"error": "name parameter required"}
                else:
                    data = db.fetch_all(
                        """SELECT mr.value, mr.timestamp, mt.unit,
                                  sr.min_value AS safe_min, sr.max_value AS safe_max
                           FROM metric_readings mr
                           JOIN metric_types mt ON mr.metric_type_id = mt.id
                           LEFT JOIN safe_ranges sr ON sr.metric_name = mt.name
                           WHERE mt.name = ?
                           ORDER BY mr.timestamp ASC""",
                        (name,),
                    )
            elif path == "/api/insight":
                data = db.fetch_one("SELECT week_start, content FROM insights ORDER BY week_start DESC LIMIT 1")
                if not data:
                    data = {"content": "No insights generated yet."}
            elif path == "/api/activity":
                data = db.fetch_all("""
                    SELECT DATE(timestamp) AS day, COUNT(*) AS count
                    FROM metric_readings
                    WHERE timestamp >= DATE('now', '-30 days')
                    GROUP BY DATE(timestamp)
                    ORDER BY day
                """)
            else:
                data = {"error": "Unknown endpoint"}

            self.wfile.write(json.dumps(data, default=str).encode())
        except Exception as e:
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default logging


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("DASHBOARD_PORT", "8090"))
    server = HTTPServer(("0.0.0.0", port), DashboardAPI)
    print(f"Dashboard API running on http://localhost:{port}")
    print(f"Dashboard: http://localhost:{port}/dashboard.html")
    print("Endpoints: /api/latest, /api/metrics, /api/readings?name=X, /api/insight, /api/activity")
    server.serve_forever()
