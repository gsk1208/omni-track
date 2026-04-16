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
import predict


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

        try:
            if path == "/api/latest":
                # Optional category filter
                category = params.get("category", [None])[0]
                filter_clause = "WHERE l.rn = 1"
                args = ()
                if category and category != "all":
                    filter_clause = "WHERE mt.category = ? AND l.rn = 1"
                    args = (category,)

                # Correctly pick the latest row per metric_type_id, even when timestamps tie.
                data = db.fetch_all(
                    f"""
                    WITH latest AS (
                        SELECT
                            mr.*,
                            ROW_NUMBER() OVER (
                                PARTITION BY mr.metric_type_id
                                ORDER BY mr.timestamp DESC, mr.id DESC
                            ) AS rn
                        FROM metric_readings mr
                    )
                    SELECT
                        mt.name, mt.display_name, mt.unit, mt.category, mt.viz_type,
                        l.value, l.timestamp, l.notes,
                        sr.min_value AS safe_min, sr.max_value AS safe_max
                    FROM latest l
                    JOIN metric_types mt ON l.metric_type_id = mt.id
                    LEFT JOIN safe_ranges sr ON sr.metric_name = mt.name
                    {filter_clause}
                    ORDER BY mt.category, mt.name
                    """,
                    args,
                )
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
            elif path == "/api/goals":
                data = db.fetch_all("""
                    SELECT mt.name AS metric_name, mt.display_name, mt.unit,
                           mg.target_value, mg.target_direction, mg.suggested_next,
                           COALESCE(s.current_streak, 0) AS current_streak,
                           COALESCE(s.longest_streak, 0) AS longest_streak,
                           s.last_active_date
                    FROM metric_goals mg
                    JOIN metric_types mt ON mg.metric_type_id = mt.id
                    LEFT JOIN streaks s ON s.metric_type_id = mt.id
                    ORDER BY s.current_streak DESC, mt.name
                """)
            elif path == "/api/correlations":
                rows = db.fetch_all("""
                    SELECT id, metrics_involved, pattern, confidence, followup_question, generated_at
                    FROM correlations
                    ORDER BY generated_at DESC
                """)
                for row in rows:
                    try:
                        row["metrics_involved"] = json.loads(row["metrics_involved"])
                    except Exception:
                        row["metrics_involved"] = []
                data = rows
            elif path == "/api/health":
                stats = db.fetch_one(
                    """SELECT
                           (SELECT COUNT(*) FROM metric_types) AS metric_types,
                           (SELECT COUNT(*) FROM metric_readings) AS readings,
                           (SELECT COUNT(*) FROM insights) AS insights,
                           (SELECT COUNT(*) FROM correlations) AS correlations,
                           (SELECT COUNT(*) FROM metric_goals) AS goals,
                           (SELECT COUNT(*) FROM streaks) AS streaks
                       """
                ) or {}
                data = {"ok": True, "db": True, **stats}
            elif path == "/api/predict":
                name = params.get("name", [None])[0]
                if not name:
                    data = {"error": "name parameter required"}
                else:
                    mt = db.fetch_one(
                        "SELECT name, display_name, unit, category, viz_type FROM metric_types WHERE name = ?",
                        (name,),
                    )
                    if not mt:
                        data = {"error": "unknown metric"}
                    else:
                        readings = db.fetch_all(
                            """SELECT mr.value, mr.timestamp
                               FROM metric_readings mr
                               JOIN metric_types mt ON mr.metric_type_id = mt.id
                               WHERE mt.name = ?
                               ORDER BY mr.timestamp ASC""",
                            (name,),
                        )

                        viz = mt.get("viz_type") or "line"
                        series = predict.as_series(readings, viz)
                        cadence = predict.detect_cadence(series)
                        fc = predict.forecast_ml(series, cadence)

                        data = {
                            "metric": mt,
                            "cadence": cadence,
                            "forecast": {
                                "model": fc.model,
                                "granularity": fc.cadence,
                                "horizon": len(fc.points),
                                "points": fc.points,
                            },
                        }
            else:
                data = {"error": "Unknown endpoint"}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, default=str).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
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
    print("Endpoints: /api/latest, /api/metrics, /api/readings?name=X, /api/insight, /api/activity, /api/health")
    server.serve_forever()
