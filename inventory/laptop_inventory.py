# laptop_inventory.py
"""
Simple Laptop Inventory App (Flask + SQLite)
- Persistent DB location: next to the exe when bundled, or next to script while developing.
- Auto-opens browser when run.
Run: python laptop_inventory.py
"""

import os
import sys
import sqlite3
from datetime import datetime
from threading import Timer
import webbrowser
from flask import Flask, g, render_template_string, request, redirect, url_for, send_file, jsonify
import csv
import io

# ---------- Paths ----------
if getattr(sys, "frozen", False):
    # running as bundled exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)

DB_PATH = os.path.join(BASE_DIR, "inventory.db")

# ---------- App ----------
app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-in-prod"

# ---------- DB helpers ----------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS laptops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE,
        brand TEXT,
        model TEXT,
        serial TEXT,
        cpu TEXT,
        ram_gb INTEGER,
        storage TEXT,
        initial_price REAL,
        selling_price REAL,
        location TEXT,
        status TEXT,
        notes TEXT,
        date_received TEXT,
        date_sold TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    db.commit()

@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# ---------- Templates ----------
BASE_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Laptop Inventory</title>
  <style>
    body{font-family:system-ui,Segoe UI,Roboto,Arial;max-width:980px;margin:24px auto;padding:0 12px}
    table{border-collapse:collapse;width:100%}
    th,td{border:1px solid #ddd;padding:8px;text-align:left}
    th{background:#f3f3f3}
    form.inline{display:inline}
    .muted{color:#666;font-size:0.9em}
    .controls{margin-bottom:12px}
    a.button, button{background:#0366d6;color:#fff;padding:6px 10px;border:none;border-radius:6px;text-decoration:none;cursor:pointer}
    a.button.secondary{background:#6c757d}
    input[type=text], input[type=number], textarea, select { width: 320px; padding:6px; margin:4px 0; }
    label { display:block; margin:6px 0; }
  </style>
</head>
<body>
  <h1><a href="{{ url_for('index') }}" style="text-decoration:none;color:inherit">Laptop Inventory</a></h1>
  <div class="controls">
    <a class="button" href="{{ url_for('add') }}">+ Add Laptop</a>
    <a class="button secondary" href="{{ url_for('export_csv') }}">Export CSV</a>
  </div>
  {% block body %}{% endblock %}
  <hr>
  <div class="muted">Simple Flask + SQLite demo. For production: add auth, backups, and HTTPS.</div>
</body>
</html>
"""

INDEX_HTML = """
{% extends "base" %}
{% block body %}
<form method="get" style="margin-bottom:12px">
  <label>Status
    <select name="status">
      <option value="">-- all --</option>
      <option value="in_stock" {% if qstatus=='in_stock' %}selected{% endif %}>In stock</option>
      <option value="sold" {% if qstatus=='sold' %}selected{% endif %}>Sold</option>
      <option value="reserved" {% if qstatus=='reserved' %}selected{% endif %}>Reserved</option>
      <option value="out_for_repair" {% if qstatus=='out_for_repair' %}selected{% endif %}>Out for repair</option>
    </select>
  </label>
  <label style="margin-left:12px">Search <input name="q" value="{{ q or '' }}"></label>
  <button>Filter</button>
</form>

<table>
  <thead><tr>
    <th>SKU</th><th>Brand / Model</th><th>Serial</th><th>Specs</th><th>Initial</th><th>Selling</th><th>Status</th><th>Location</th><th>Actions</th>
  </tr></thead>
  <tbody>
    {% for r in items %}
    <tr>
      <td>{{ r['sku'] }}</td>
      <td><strong>{{ r['brand'] }}</strong><br>{{ r['model'] }}</td>
      <td>{{ r['serial'] or '' }}</td>
      <td>{{ r['cpu'] or '' }} / {{ r['ram_gb'] or '' }}GB / {{ r['storage'] or '' }}</td>
      <td>${{ '%.2f'|format(r['initial_price'] or 0) }}</td>
      <td>${{ '%.2f'|format(r['selling_price'] or 0) }}</td>
      <td>{{ r['status'] or '' }}</td>
      <td>{{ r['location'] or '' }}</td>
      <td>
        <a href="{{ url_for('edit', item_id=r['id']) }}">Edit</a> |
        <form class="inline" method="post" action="{{ url_for('toggle_out', item_id=r['id']) }}" style="display:inline">
          {% if r['status']!='sold' %}
            <button type="submit">Mark as Sold</button>
          {% else %}
            <button type="submit">Mark In Stock</button>
          {% endif %}
        </form> |
        <form class="inline" method="post" action="{{ url_for('delete', item_id=r['id']) }}" onsubmit="return confirm('Delete this item?');">
          <button type="submit" style="background:#d9534f">Delete</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan=9 class="muted">No items found.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
"""

FORM_HTML = """
{% extends "base" %}
{% block body %}
<h2>{{ 'Edit' if item else 'Add' }} Laptop</h2>
<form method="post">
  <label>SKU: <input name="sku" value="{{ item.sku if item else '' }}" required></label>
  <label>Brand: <input name="brand" value="{{ item.brand if item else '' }}"></label>
  <label>Model: <input name="model" value="{{ item.model if item else '' }}"></label>
  <label>Serial: <input name="serial" value="{{ item.serial if item else '' }}"></label>
  <label>CPU: <input name="cpu" value="{{ item.cpu if item else '' }}"></label>
  <label>RAM (GB): <input type="number" name="ram_gb" value="{{ item.ram_gb if item else '' }}"></label>
  <label>Storage: <input name="storage" value="{{ item.storage if item else '' }}"></label>
  <label>Initial price: <input type="number" step="0.01" name="initial_price" value="{{ item.initial_price if item else '' }}"></label>
  <label>Selling price: <input type="number" step="0.01" name="selling_price" value="{{ item.selling_price if item else '' }}"></label>
  <label>Location: <input name="location" value="{{ item.location if item else '' }}"></label>
  <label>Status:
    <select name="status">
      <option value="in_stock" {% if item and item.status=='in_stock' %}selected{% endif %}>in_stock</option>
      <option value="sold" {% if item and item.status=='sold' %}selected{% endif %}>sold</option>
      <option value="reserved" {% if item and item.status=='reserved' %}selected{% endif %}>reserved</option>
      <option value="out_for_repair" {% if item and item.status=='out_for_repair' %}selected{% endif %}>out_for_repair</option>
    </select>
  </label>
  <label>Notes:<br><textarea name="notes" rows="3" cols="60">{{ item.notes if item else '' }}</textarea></label><br><br>
  <button type="submit">Save</button>
  <a href="{{ url_for('index') }}" class="button secondary">Cancel</a>
</form>
{% endblock %}
"""

# register templates
app.jinja_loader.mapping = {
    "base": BASE_HTML,
    "index.html": INDEX_HTML,
    "form.html": FORM_HTML
}

# ---------- Routes ----------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    db = get_db()
    sql = "SELECT * FROM laptops"
    params = []
    where = []
    if status:
        where.append("status = ?")
        params.append(status)
    if q:
        where.append("(sku LIKE ? OR brand LIKE ? OR model LIKE ? OR serial LIKE ?)")
        v = f"%{q}%"
        params.extend([v, v, v, v])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT 1000"
    items = db.execute(sql, params).fetchall()
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, "index.html")[0], items=items, q=q, qstatus=status)

@app.route("/add", methods=["GET", "POST"])
def add():
    db = get_db()
    if request.method == "POST":
        data = dict(
            sku=request.form.get("sku").strip(),
            brand=request.form.get("brand").strip(),
            model=request.form.get("model").strip(),
            serial=request.form.get("serial").strip(),
            cpu=request.form.get("cpu").strip(),
            ram_gb=request.form.get("ram_gb") or None,
            storage=request.form.get("storage").strip(),
            initial_price=request.form.get("initial_price") or None,
            selling_price=request.form.get("selling_price") or None,
            location=request.form.get("location").strip(),
            status=request.form.get("status") or "in_stock",
            notes=request.form.get("notes").strip(),
            date_received=datetime.utcnow().isoformat()
        )
        db.execute("""
            INSERT INTO laptops (sku,brand,model,serial,cpu,ram_gb,storage,initial_price,selling_price,location,status,notes,date_received)
            VALUES (:sku,:brand,:model,:serial,:cpu,:ram_gb,:storage,:initial_price,:selling_price,:location,:status,:notes,:date_received)
        """, data)
        db.commit()
        return redirect(url_for("index"))
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, "form.html")[0], item=None)

@app.route("/edit/<int:item_id>", methods=["GET", "POST"])
def edit(item_id):
    db = get_db()
    row = db.execute("SELECT * FROM laptops WHERE id = ?", (item_id,)).fetchone()
    if not row:
        return "Not found", 404
    if request.method == "POST":
        db.execute("""
            UPDATE laptops SET sku=?,brand=?,model=?,serial=?,cpu=?,ram_gb=?,storage=?,initial_price=?,selling_price=?,location=?,status=?,notes=?
            WHERE id=?
        """, (
            request.form.get("sku").strip(),
            request.form.get("brand").strip(),
            request.form.get("model").strip(),
            request.form.get("serial").strip(),
            request.form.get("cpu").strip(),
            request.form.get("ram_gb") or None,
            request.form.get("storage").strip(),
            request.form.get("initial_price") or None,
            request.form.get("selling_price") or None,
            request.form.get("location").strip(),
            request.form.get("status") or "in_stock",
            request.form.get("notes").strip(),
            item_id
        ))
        db.commit()
        return redirect(url_for("index"))
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, "form.html")[0], item=row)

@app.route("/toggle_out/<int:item_id>", methods=["POST"])
def toggle_out(item_id):
    db = get_db()
    row = db.execute("SELECT status FROM laptops WHERE id=?", (item_id,)).fetchone()
    if not row:
        return "Not found", 404
    new_status = "in_stock" if row["status"] == "sold" else "sold"
    date_sold = datetime.utcnow().isoformat() if new_status == "sold" else None
    db.execute("UPDATE laptops SET status=?, date_sold=? WHERE id=?", (new_status, date_sold, item_id))
    db.commit()
    return redirect(url_for("index"))

@app.route("/delete/<int:item_id>", methods=["POST"])
def delete(item_id):
    db = get_db()
    db.execute("DELETE FROM laptops WHERE id=?", (item_id,))
    db.commit()
    return redirect(url_for("index"))

# CSV export
@app.route("/export")
def export_csv():
    db = get_db()
    rows = db.execute("SELECT * FROM laptops ORDER BY created_at DESC").fetchall()
    si = io.StringIO()
    writer = csv.writer(si)
    header = ["id","sku","brand","model","serial","cpu","ram_gb","storage","initial_price","selling_price","location","status","notes","date_received","date_sold","created_at"]
    writer.writerow(header)
    for r in rows:
        writer.writerow([r[h] for h in header])
    mem = io.BytesIO()
    mem.write(si.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="laptops.csv")

# Simple JSON API (basic, no auth)
@app.route("/api/items", methods=["GET","POST"])
def api_items():
    db = get_db()
    if request.method == "GET":
        rows = db.execute("SELECT * FROM laptops ORDER BY created_at DESC LIMIT 1000").fetchall()
        return jsonify([dict(r) for r in rows])
    else:
        payload = request.json or {}
        if "sku" not in payload:
            return jsonify({"error":"sku required"}), 400
        db.execute("""
            INSERT INTO laptops (sku,brand,model,serial,cpu,ram_gb,storage,initial_price,selling_price,location,status,notes,date_received)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            payload.get("sku"),
            payload.get("brand"),
            payload.get("model"),
            payload.get("serial"),
            payload.get("cpu"),
            payload.get("ram_gb"),
            payload.get("storage"),
            payload.get("initial_price"),
            payload.get("selling_price"),
            payload.get("location"),
            payload.get("status","in_stock"),
            payload.get("notes"),
            datetime.utcnow().isoformat()
        ))
        db.commit()
        return jsonify({"ok":True}), 201

# ---------- Run ----------
if __name__ == "__main__":
    with app.app_context():
        init_db()

    host = "127.0.0.1"
    port = 5000

    def open_browser():
        webbrowser.open(f"http://{host}:{port}/")

    # open browser after short delay when running locally
    Timer(1.0, open_browser).start()
    app.run(host=host, port=port, debug=False)