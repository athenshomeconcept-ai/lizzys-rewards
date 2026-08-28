
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, Response
import os, io, secrets, uuid, csv
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None

import sqlite3

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = os.path.join(BASE_DIR, "lizzys.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE","0") == "1",
)
STAMP_GOAL = int(os.environ.get("STAMP_GOAL", "8"))
APP_NAME = "Lizzy’s Rewards"

def is_pg():
    return DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")

def connect():
    if is_pg():
        if not psycopg:
            raise RuntimeError("psycopg is not installed")
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def qmark(sql):
    return sql.replace("?", "%s") if is_pg() else sql

def execute(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(qmark(sql), params)
    return cur

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    conn = connect()
    c = conn.cursor()
    if is_pg():
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS members(
            id SERIAL PRIMARY KEY,
            member_code TEXT UNIQUE NOT NULL,
            token TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            email TEXT,
            birthday TEXT,
            stamps INTEGER NOT NULL DEFAULT 0,
            rewards INTEGER NOT NULL DEFAULT 0,
            redeemed INTEGER NOT NULL DEFAULT 0,
            consent_marketing INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS activity(
            id SERIAL PRIMARY KEY,
            member_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS offers(
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )""")
    else:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS members(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_code TEXT UNIQUE NOT NULL,
            token TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            email TEXT,
            birthday TEXT,
            stamps INTEGER NOT NULL DEFAULT 0,
            rewards INTEGER NOT NULL DEFAULT 0,
            redeemed INTEGER NOT NULL DEFAULT 0,
            consent_marketing INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activity(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS offers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)
    conn.commit()

    admin_user = os.environ.get("ADMIN_USER", "admin")
    admin_pass = os.environ.get("ADMIN_PASSWORD", "CHANGE-ME-ADMIN")
    staff_user = os.environ.get("STAFF_USER", "staff")
    staff_pass = os.environ.get("STAFF_PASSWORD", "CHANGE-ME-STAFF")

    for username, pwd, role in [(admin_user, admin_pass, "admin"), (staff_user, staff_pass, "staff")]:
        try:
            execute(conn, "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                    (username, generate_password_hash(pwd), role, now()))
            conn.commit()
        except Exception:
            conn.rollback()

    # seed offer
    cur = execute(conn, "SELECT COUNT(*) AS n FROM offers")
    row = cur.fetchone()
    n = row["n"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
    if n == 0:
        execute(conn, "INSERT INTO offers(title,description,active,created_at) VALUES(?,?,?,?)",
                ("Διπλές σφραγίδες", "15:00–18:00 σε επιλεγμένες ημέρες.", 1, now()))
        conn.commit()
    conn.close()

def fetchone(sql, params=()):
    conn = connect()
    row = execute(conn, sql, params).fetchone()
    conn.close()
    return row

def fetchall(sql, params=()):
    conn = connect()
    rows = execute(conn, sql, params).fetchall()
    conn.close()
    return rows

def log_activity(member_id, action, details=""):
    conn = connect()
    execute(conn, "INSERT INTO activity(member_id,action,details,created_at) VALUES(?,?,?,?)",
            (member_id, action, details, now()))
    conn.commit()
    conn.close()

def require_role(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if session.get("role") not in roles:
                return redirect(url_for("login"))
            return fn(*args, **kwargs)
        return wrapper
    return deco

@app.before_request
def ensure_db():
    if not getattr(app, "_db_ready", False):
        init_db()
        app._db_ready = True

@app.route("/")
def home():
    offers = fetchall("SELECT * FROM offers WHERE active=1 ORDER BY id DESC LIMIT 3")
    return render_template("home.html", offers=offers)

@app.route("/join", methods=["GET","POST"])
def join():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        phone = request.form.get("phone","").strip().replace(" ","")
        email = request.form.get("email","").strip()
        birthday = request.form.get("birthday","").strip() or None
        consent = 1 if request.form.get("consent_marketing") == "on" else 0
        if not name or not phone:
            flash("Συμπλήρωσε όνομα και κινητό.", "error")
            return render_template("join.html")
        existing = fetchone("SELECT * FROM members WHERE phone=?", (phone,))
        if existing:
            return redirect(url_for("card", token=existing["token"]))
        conn = connect()
        cur = execute(conn, "SELECT COUNT(*) AS n FROM members")
        r = cur.fetchone()
        count = r["n"] if hasattr(r,"keys") else r[0]
        code = f"LZ-{1001+count}"
        token = uuid.uuid4().hex + uuid.uuid4().hex[:8]
        execute(conn, """INSERT INTO members(member_code,token,name,phone,email,birthday,stamps,rewards,redeemed,consent_marketing,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (code,token,name,phone,email,birthday,0,0,0,consent,now()))
        conn.commit()
        member = execute(conn, "SELECT * FROM members WHERE phone=?", (phone,)).fetchone()
        conn.close()
        log_activity(member["id"], "member_created", "Νέα εγγραφή")
        return redirect(url_for("card", token=token))
    return render_template("join.html")

@app.route("/card/<token>")
def card(token):
    member = fetchone("SELECT * FROM members WHERE token=?", (token,))
    if not member: return "Η κάρτα δεν βρέθηκε.", 404
    available = member["rewards"] + (1 if member["stamps"] >= STAMP_GOAL else 0)
    offers = fetchall("SELECT * FROM offers WHERE active=1 ORDER BY id DESC LIMIT 5")
    return render_template("card.html", member=member, goal=STAMP_GOAL, available=available, offers=offers)

@app.route("/qr/<token>")
def qr(token):
    member = fetchone("SELECT * FROM members WHERE token=?", (token,))
    if not member: return "Not found", 404
    url = request.url_root.rstrip("/") + url_for("card", token=token)
    img = qrcode.make(url)
    bio = io.BytesIO(); img.save(bio, "PNG"); bio.seek(0)
    return send_file(bio, mimetype="image/png", download_name="lizzys-member-qr.png")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        user = fetchone("SELECT * FROM users WHERE username=?", (username,))
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"]=user["id"]; session["username"]=user["username"]; session["role"]=user["role"]
            return redirect(url_for("dashboard" if user["role"]=="admin" else "staff"))
        flash("Λάθος στοιχεία σύνδεσης.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/staff")
@require_role("staff","admin")
def staff():
    q = request.args.get("q","").strip()
    members=[]
    if q:
        like=f"%{q}%"
        members=fetchall("""SELECT * FROM members WHERE name LIKE ? OR phone LIKE ? OR member_code LIKE ? OR token LIKE ?
                            ORDER BY name LIMIT 20""",(like,like,like,like))
    return render_template("staff.html", members=members, q=q, goal=STAMP_GOAL)

@app.post("/staff/member/<int:member_id>/stamp")
@require_role("staff","admin")
def add_stamp(member_id):
    m=fetchone("SELECT * FROM members WHERE id=?", (member_id,))
    if not m: return "Not found",404
    if m["stamps"]>=STAMP_GOAL:
        flash("Υπάρχει ήδη διαθέσιμο δώρο. Κάνε πρώτα εξαργύρωση.","error")
        return redirect(url_for("staff",q=m["member_code"]))
    conn=connect(); execute(conn,"UPDATE members SET stamps=stamps+1 WHERE id=?",(member_id,)); conn.commit(); conn.close()
    log_activity(member_id,"stamp_added",f"+1 stamp από {session.get('username')}")
    flash("Η σφραγίδα προστέθηκε.","success")
    return redirect(url_for("staff",q=m["member_code"]))

@app.post("/staff/member/<int:member_id>/redeem")
@require_role("staff","admin")
def redeem(member_id):
    m=fetchone("SELECT * FROM members WHERE id=?", (member_id,))
    if not m: return "Not found",404
    conn=connect()
    if m["stamps"]>=STAMP_GOAL:
        execute(conn,"UPDATE members SET stamps=0, redeemed=redeemed+1 WHERE id=?",(member_id,))
    elif m["rewards"]>0:
        execute(conn,"UPDATE members SET rewards=rewards-1, redeemed=redeemed+1 WHERE id=?",(member_id,))
    else:
        conn.close(); flash("Δεν υπάρχει διαθέσιμο δώρο.","error"); return redirect(url_for("staff",q=m["member_code"]))
    conn.commit(); conn.close()
    log_activity(member_id,"reward_redeemed",f"Εξαργύρωση από {session.get('username')}")
    flash("Η εξαργύρωση ολοκληρώθηκε.","success")
    return redirect(url_for("staff",q=m["member_code"]))

@app.route("/admin")
@require_role("admin")
def dashboard():
    stats = {
        "members": fetchone("SELECT COUNT(*) AS n FROM members")["n"],
        "stamps": fetchone("SELECT COALESCE(SUM(stamps),0) AS n FROM members")["n"],
        "redeemed": fetchone("SELECT COALESCE(SUM(redeemed),0) AS n FROM members")["n"],
        "ready": fetchone("SELECT COUNT(*) AS n FROM members WHERE stamps>=?",(STAMP_GOAL,))["n"],
    }
    members=fetchall("SELECT * FROM members ORDER BY id DESC LIMIT 200")
    activity=fetchall("""SELECT activity.*, members.name, members.member_code FROM activity
                         LEFT JOIN members ON members.id=activity.member_id ORDER BY activity.id DESC LIMIT 50""")
    offers=fetchall("SELECT * FROM offers ORDER BY id DESC")
    return render_template("admin.html", stats=stats, members=members, activity=activity, offers=offers, goal=STAMP_GOAL)

@app.post("/admin/offers")
@require_role("admin")
def add_offer():
    title=request.form.get("title","").strip()
    description=request.form.get("description","").strip()
    if title:
        conn=connect(); execute(conn,"INSERT INTO offers(title,description,active,created_at) VALUES(?,?,?,?)",(title,description,1,now())); conn.commit(); conn.close()
        flash("Η προσφορά δημιουργήθηκε.","success")
    return redirect(url_for("dashboard"))

@app.post("/admin/offers/<int:offer_id>/toggle")
@require_role("admin")
def toggle_offer(offer_id):
    conn=connect(); execute(conn,"UPDATE offers SET active=CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?",(offer_id,)); conn.commit(); conn.close()
    return redirect(url_for("dashboard"))

@app.route("/admin/export/members.csv")
@require_role("admin")
def export_members():
    rows=fetchall("SELECT member_code,name,phone,email,birthday,stamps,rewards,redeemed,consent_marketing,created_at FROM members ORDER BY id")
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["member_code","name","phone","email","birthday","stamps","rewards","redeemed","consent_marketing","created_at"])
    for r in rows:
        w.writerow([r[k] for k in ["member_code","name","phone","email","birthday","stamps","rewards","redeemed","consent_marketing","created_at"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=lizzys-members.csv"})

@app.route("/health")
def health():
    return jsonify({"status":"ok","app":APP_NAME,"database":"postgres" if is_pg() else "sqlite"})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","8000")), debug=os.environ.get("FLASK_DEBUG")=="1")
