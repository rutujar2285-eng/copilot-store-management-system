import os
import sqlite3
import io
import json
import shutil
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

APP_NAME = "DIVINE STORE MANAGEMENT"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.environ.get("DIVINE_STORE_DB", os.path.join(BASE_DIR, "instance", "divine_store.db"))
SECRET_KEY = os.environ.get("DIVINE_STORE_SECRET", "change-this-secret-before-production")

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            plant TEXT NOT NULL DEFAULT 'ADMIN',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name_en TEXT NOT NULL,
            name_mr TEXT DEFAULT '',
            category TEXT DEFAULT '',
            unit TEXT NOT NULL DEFAULT 'Nos',
            location TEXT DEFAULT '',
            min_stock REAL NOT NULL DEFAULT 0,
            quantity REAL NOT NULL DEFAULT 0,
            purchase_price REAL NOT NULL DEFAULT 0,
            supplier TEXT DEFAULT '',
            plant TEXT NOT NULL DEFAULT 'ADMIN',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stock_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            txn_type TEXT NOT NULL CHECK(txn_type IN ('IN','OUT','ADJUST')),
            quantity REAL NOT NULL,
            reference TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_by TEXT NOT NULL,
            plant TEXT NOT NULL DEFAULT 'ADMIN',
            created_at TEXT NOT NULL,
            FOREIGN KEY(item_id) REFERENCES items(id)
        );
        CREATE TABLE IF NOT EXISTS raw_material_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rm_name TEXT NOT NULL,
            rm_grade TEXT DEFAULT '',
            color TEXT DEFAULT '',
            hsn TEXT DEFAULT '',
            party_name TEXT DEFAULT '',
            min_qty REAL NOT NULL DEFAULT 0,
            max_qty REAL NOT NULL DEFAULT 0,
            opening_stock REAL NOT NULL DEFAULT 0,
            opening_date TEXT DEFAULT '',
            plant TEXT NOT NULL DEFAULT 'ADMIN',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS poly_bag_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poly_bag_size TEXT NOT NULL,
            party_name TEXT DEFAULT '',
            hsn TEXT DEFAULT '',
            min_qty REAL NOT NULL DEFAULT 0,
            max_qty REAL NOT NULL DEFAULT 0,
            opening_stock REAL NOT NULL DEFAULT 0,
            opening_date TEXT DEFAULT '',
            plant TEXT NOT NULL DEFAULT 'ADMIN',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bop_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            party_name TEXT DEFAULT '',
            min_qty REAL NOT NULL DEFAULT 0,
            max_qty REAL NOT NULL DEFAULT 0,
            opening_stock REAL NOT NULL DEFAULT 0,
            opening_date TEXT DEFAULT '',
            plant TEXT NOT NULL DEFAULT 'ADMIN',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS requisitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requisition_no TEXT UNIQUE NOT NULL,
            plant TEXT NOT NULL,
            mold_no TEXT NOT NULL,
            machine_no TEXT NOT NULL,
            supervisor TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            store_by TEXT DEFAULT '',
            finalized_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS requisition_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requisition_id INTEGER NOT NULL,
            material_kind TEXT NOT NULL,
            master_id INTEGER NOT NULL,
            material_name TEXT NOT NULL,
            grade TEXT DEFAULT '',
            color TEXT DEFAULT '',
            party_name TEXT DEFAULT '',
            requested_qty REAL NOT NULL,
            issued_qty REAL NOT NULL DEFAULT 0,
            available_at_request REAL NOT NULL DEFAULT 0,
            plant TEXT NOT NULL,
            FOREIGN KEY(requisition_id) REFERENCES requisitions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS material_issue_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requisition_id INTEGER NOT NULL,
            requisition_line_id INTEGER NOT NULL,
            material_kind TEXT NOT NULL,
            master_id INTEGER NOT NULL,
            quantity REAL NOT NULL,
            plant TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(requisition_id) REFERENCES requisitions(id),
            FOREIGN KEY(requisition_line_id) REFERENCES requisition_lines(id)
        );
        CREATE TABLE IF NOT EXISTS grn_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, grn_no TEXT UNIQUE NOT NULL,
            material_kind TEXT NOT NULL, party_name TEXT NOT NULL, invoice_no TEXT NOT NULL,
            invoice_date TEXT NOT NULL, vehicle_no TEXT DEFAULT '', po_no TEXT DEFAULT '',
            grn_date TEXT NOT NULL, saved_at TEXT NOT NULL, created_by TEXT NOT NULL,
            tc_received INTEGER NOT NULL DEFAULT 0, eway_received INTEGER NOT NULL DEFAULT 0,
            plant TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS grn_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, grn_id INTEGER NOT NULL,
            material_kind TEXT NOT NULL, master_id INTEGER NOT NULL, lot_no TEXT NOT NULL,
            quantity REAL NOT NULL, packing TEXT DEFAULT '', plant TEXT NOT NULL,
            FOREIGN KEY(grn_id) REFERENCES grn_entries(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS lot_issue_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, issue_transaction_id INTEGER NOT NULL,
            lot_no TEXT NOT NULL, quantity REAL NOT NULL,
            FOREIGN KEY(issue_transaction_id) REFERENCES material_issue_transactions(id) ON DELETE CASCADE
        );
        """)
        # Migrate older databases without plant columns.
        for table in ("users", "items", "stock_transactions", "raw_material_master", "poly_bag_master", "bop_master"):
            cols = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
            if "plant" not in cols:
                db.execute(f"ALTER TABLE {table} ADD COLUMN plant TEXT NOT NULL DEFAULT 'ADMIN'")
        now = datetime.now().isoformat(timespec="seconds")
        # Upgrade the old starter account once, then preserve any future password changes.
        legacy = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        existing_admin = db.execute("SELECT id FROM users WHERE username='ADMIN'").fetchone()
        if legacy and not existing_admin:
            db.execute("UPDATE users SET username='ADMIN', password_hash=?, role='admin', plant='ADMIN' WHERE id=?",
                       (generate_password_hash("ADMIN१२३"), legacy["id"]))
        initial_users = [
            ("ADMIN", "ADMIN१२३", "admin", "ADMIN"),
            ("SACHIN", "SACHIN१२३", "staff", "J BLOCK"),
            ("LASURKAR", "LASURKAR१२३", "staff", "F-2 BLOCK"),
            ("MATHOW", "MATHOW१२३", "staff", "T BLOCK"),
            ("CHATAN", "CHATAN१२३", "staff", "S BLOCK"),
        ]
        for username, password, role, plant in initial_users:
            if not db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                db.execute("INSERT INTO users(username,password_hash,role,plant,created_at) VALUES(?,?,?,?,?)",
                           (username, generate_password_hash(password), role, plant, now))

@app.before_request
def before_request():
    g.user = session.get("user")

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def plant_scope(alias=""):
    """Return SQL condition and parameters for current user's plant scope."""
    if session.get("role") == "admin":
        return "1=1", []
    col = f"{alias}.plant" if alias else "plant"
    return f"{col} = ?", [session.get("plant", "ADMIN")]

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("या कामासाठी Admin permission आवश्यक आहे. / Admin permission required.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped

@app.context_processor
def inject_globals():
    return {"app_name": APP_NAME, "current_user": session.get("user"), "current_role": session.get("role"), "current_plant": session.get("plant", "ADMIN")}

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with connect_db() as db:
            user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user"] = user["username"]
            session["role"] = user["role"]
            session["plant"] = user["plant"] if "plant" in user.keys() else "ADMIN"
            flash("Login successful / लॉगिन यशस्वी", "success")
            return redirect(url_for("dashboard"))
        flash("चुकीचे Username किंवा Password / Invalid username or password", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("तुम्ही सुरक्षितपणे Logout केले आहे. / Logged out.", "success")
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    with connect_db() as db:
        scope, params = plant_scope()
        total_items = db.execute(f"SELECT COUNT(*) FROM items WHERE {scope}", params).fetchone()[0]
        total_qty = db.execute(f"SELECT COALESCE(SUM(quantity),0) FROM items WHERE {scope}", params).fetchone()[0]
        low_stock = db.execute(f"SELECT * FROM items WHERE quantity <= min_stock AND {scope} ORDER BY name_en LIMIT 8", params).fetchall()
        t_scope, t_params = plant_scope("t")
        recent = db.execute(f"""SELECT t.*, i.code, i.name_en FROM stock_transactions t
                               JOIN items i ON i.id=t.item_id WHERE {t_scope} ORDER BY t.id DESC LIMIT 8""", t_params).fetchall()
    return render_template("dashboard.html", total_items=total_items, total_qty=total_qty, low_stock=low_stock, recent=recent)

@app.route("/items")
@login_required
def items():
    q = request.args.get("q", "").strip()
    with connect_db() as db:
        scope, params = plant_scope()
        rows = db.execute(f"""SELECT * FROM items
            WHERE ({scope}) AND (code LIKE ? OR name_en LIKE ? OR name_mr LIKE ? OR category LIKE ?)
            ORDER BY name_en""", tuple(params + [f"%{q}%"]*4)).fetchall()
    return render_template("items.html", items=rows, q=q)

@app.route("/items/new", methods=["GET", "POST"])
@login_required
def item_new():
    if request.method == "POST":
        data = collect_item_form()
        if not data["code"] or not data["name_en"]:
            flash("Item Code आणि English Name आवश्यक आहेत. / Required fields missing.", "error")
            return render_template("item_form.html", item=data, page_title="नवीन Item / New Item")
        target_plant = request.form.get("plant", session.get("plant", "ADMIN")) if session.get("role") == "admin" else session.get("plant", "ADMIN")
        if target_plant not in ("ADMIN", "J BLOCK", "F-2 BLOCK", "T BLOCK", "S BLOCK"):
            target_plant = session.get("plant", "ADMIN")
        try:
            with connect_db() as db:
                db.execute("""INSERT INTO items
                    (code,name_en,name_mr,category,unit,location,min_stock,quantity,purchase_price,supplier,plant,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (data["code"],data["name_en"],data["name_mr"],data["category"],data["unit"],data["location"],
                     data["min_stock"],data["quantity"],data["purchase_price"],data["supplier"],target_plant,
                     datetime.now().isoformat(timespec="seconds")))
                item_id = db.execute("SELECT id FROM items WHERE code=?", (data["code"],)).fetchone()["id"]
                if data["quantity"] > 0:
                    db.execute("""INSERT INTO stock_transactions(item_id,txn_type,quantity,reference,notes,created_by,plant,created_at)
                                  VALUES(?,?,?,?,?,?,?,?)""",
                               (item_id,"IN",data["quantity"],"OPENING","Opening stock",session["user"],target_plant,datetime.now().isoformat(timespec="seconds")))
            flash("Item तयार झाला. / Item created.", "success")
            return redirect(url_for("items"))
        except sqlite3.IntegrityError:
            flash("हा Item Code आधीच वापरला आहे. / Item code already exists.", "error")
    return render_template("item_form.html", item={}, page_title="नवीन Item / New Item")

def collect_item_form():
    def num(key, default=0):
        try: return max(0, float(request.form.get(key, default) or default))
        except ValueError: return float(default)
    return {
        "code": request.form.get("code","").strip(),
        "name_en": request.form.get("name_en","").strip(),
        "name_mr": request.form.get("name_mr","").strip(),
        "category": request.form.get("category","").strip(),
        "unit": request.form.get("unit","Nos").strip() or "Nos",
        "location": request.form.get("location","").strip(),
        "min_stock": num("min_stock"),
        "quantity": num("quantity"),
        "purchase_price": num("purchase_price"),
        "supplier": request.form.get("supplier","").strip()
    }

@app.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def item_edit(item_id):
    with connect_db() as db:
        scope, scope_params = plant_scope()
        item = db.execute(f"SELECT * FROM items WHERE id=? AND {scope}", (item_id, *scope_params)).fetchone()
        if not item:
            flash("Item सापडला नाही. / Item not found.", "error")
            return redirect(url_for("items"))
        if request.method == "POST":
            data = collect_item_form()
            try:
                db.execute("""UPDATE items SET code=?,name_en=?,name_mr=?,category=?,unit=?,location=?,
                    min_stock=?,purchase_price=?,supplier=? WHERE id=? AND plant=?""",
                    (data["code"],data["name_en"],data["name_mr"],data["category"],data["unit"],data["location"],
                     data["min_stock"],data["purchase_price"],data["supplier"],item_id,item["plant"]))
                flash("Item अपडेट झाला. / Item updated.", "success")
                return redirect(url_for("items"))
            except sqlite3.IntegrityError:
                flash("हा Item Code दुसऱ्या Item साठी वापरला आहे. / Duplicate item code.", "error")
    return render_template("item_form.html", item=dict(item), page_title="Item संपादन / Edit Item", editing=True)

@app.route("/stock", methods=["GET", "POST"])
@login_required
def stock():
    with connect_db() as db:
        if request.method == "POST":
            try:
                item_id = int(request.form.get("item_id", "0"))
                txn_type = request.form.get("txn_type", "")
                qty = float(request.form.get("quantity", "0"))
                reference = request.form.get("reference","").strip()
                notes = request.form.get("notes","").strip()
                scope, scope_params = plant_scope()
                item = db.execute(f"SELECT * FROM items WHERE id=? AND {scope}", (item_id, *scope_params)).fetchone()
                if not item or txn_type not in ("IN","OUT") or qty <= 0:
                    raise ValueError("Invalid stock transaction")
                if txn_type == "OUT" and qty > item["quantity"]:
                    flash("उपलब्ध Stock पेक्षा जास्त Issue करता येणार नाही. / Insufficient stock.", "error")
                else:
                    delta = qty if txn_type == "IN" else -qty
                    db.execute("UPDATE items SET quantity=quantity+? WHERE id=?", (delta,item_id))
                    db.execute("""INSERT INTO stock_transactions(item_id,txn_type,quantity,reference,notes,created_by,plant,created_at)
                                  VALUES(?,?,?,?,?,?,?,?)""",
                               (item_id,txn_type,qty,reference,notes,session["user"],item["plant"],datetime.now().isoformat(timespec="seconds")))
                    flash("Stock transaction नोंदवला. / Stock transaction saved.", "success")
                    return redirect(url_for("stock"))
            except (ValueError, TypeError):
                flash("कृपया योग्य Item आणि Quantity द्या. / Enter a valid item and quantity.", "error")
        scope, params = plant_scope()
        items_list = db.execute(f"SELECT id,code,name_en,quantity,unit FROM items WHERE {scope} ORDER BY name_en", params).fetchall()
        t_scope, t_params = plant_scope("t")
        transactions = db.execute(f"""SELECT t.*,i.code,i.name_en FROM stock_transactions t
                                     JOIN items i ON i.id=t.item_id WHERE {t_scope} ORDER BY t.id DESC LIMIT 100""", t_params).fetchall()
    return render_template("stock.html", items=items_list, transactions=transactions)

@app.route("/reports")
@login_required
def reports():
    with connect_db() as db:
        scope, params = plant_scope()
        rows = db.execute(f"SELECT * FROM items WHERE {scope} ORDER BY category,name_en", params).fetchall()
        low_count = db.execute(f"SELECT COUNT(*) FROM items WHERE quantity <= min_stock AND {scope}", params).fetchone()[0]
        stock_value = db.execute(f"SELECT COALESCE(SUM(quantity*purchase_price),0) FROM items WHERE {scope}", params).fetchone()[0]
    return render_template("reports.html", items=rows, low_count=low_count, stock_value=stock_value)

@app.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    with connect_db() as db:
        if request.method == "POST":
            username = request.form.get("username","").strip()
            password = request.form.get("password","")
            role = request.form.get("role","staff")
            plant = request.form.get("plant","J BLOCK")
            allowed_plants = ("ADMIN", "J BLOCK", "F-2 BLOCK", "T BLOCK", "S BLOCK")
            if not username or len(password) < 8 or role not in ("admin","staff") or plant not in allowed_plants:
                flash("Username, Plant आणि किमान 8 अक्षरांचा Password द्या. / Check username, plant and password.", "error")
            else:
                try:
                    db.execute("INSERT INTO users(username,password_hash,role,plant,created_at) VALUES(?,?,?,?,?)",
                               (username,generate_password_hash(password),role,plant,datetime.now().isoformat(timespec="seconds")))
                    flash("User तयार झाला. / User created.", "success")
                    return redirect(url_for("users"))
                except sqlite3.IntegrityError:
                    flash("Username आधीच अस्तित्वात आहे. / Username already exists.", "error")
        all_users = db.execute("SELECT id,username,role,plant,created_at FROM users ORDER BY id").fetchall()
    return render_template("users.html", users=all_users)

@app.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id):
    if user_id == 1:
        flash("Default admin user delete करता येत नाही. / Cannot delete initial admin.", "error")
    elif session.get("user"):
        with connect_db() as db:
            target = db.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
            if target and target["username"] == session.get("user"):
                flash("स्वतःचा User delete करता येणार नाही. / Cannot delete your own user.", "error")
            else:
                db.execute("DELETE FROM users WHERE id=?", (user_id,))
                flash("User delete झाला. / User deleted.", "success")
    return redirect(url_for("users"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        with connect_db() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (session["user"],)).fetchone()
            if not user or not check_password_hash(user["password_hash"], current):
                flash("सध्याचा Password चुकीचा आहे. / Current password is incorrect.", "error")
            elif len(new) < 8:
                flash("नवीन Password किमान 8 अक्षरांचा असावा. / Password must be at least 8 characters.", "error")
            elif new != confirm:
                flash("दोन्ही नवीन Password जुळत नाहीत. / New passwords do not match.", "error")
            else:
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), user["id"]))
                flash("Password यशस्वीपणे बदलला. / Password changed successfully.", "success")
                return redirect(url_for("dashboard"))
    return render_template("change_password.html")

MATERIAL_MASTER_TABLES = {
    "RAW": ("raw_material_master", "rm_name"),
    "POLY BAG": ("poly_bag_master", "poly_bag_size"),
    "BOP": ("bop_master", "description"),
}


def material_current_stock(db, kind, master_id, plant):
    table, _ = MATERIAL_MASTER_TABLES[kind]
    row = db.execute(f"SELECT opening_stock FROM {table} WHERE id=? AND plant=?", (master_id, plant)).fetchone()
    if not row:
        return None
    received = db.execute("SELECT COALESCE(SUM(quantity),0) FROM grn_lines WHERE material_kind=? AND master_id=? AND plant=?", (kind, master_id, plant)).fetchone()[0]
    issued = db.execute("SELECT COALESCE(SUM(quantity),0) FROM material_issue_transactions WHERE material_kind=? AND master_id=? AND plant=?", (kind, master_id, plant)).fetchone()[0]
    return max(0.0, float(row["opening_stock"] or 0) + float(received or 0) - float(issued or 0))


def lot_stock_rows(db, kind, master_id, plant):
    table, _ = MATERIAL_MASTER_TABLES[kind]
    master = db.execute(f"SELECT opening_stock, opening_date FROM {table} WHERE id=? AND plant=?", (master_id, plant)).fetchone()
    lots = []
    if master and float(master["opening_stock"] or 0) > 0:
        lots.append({"lot_no":"OPENING", "received":float(master["opening_stock"]), "issued":0.0, "balance":float(master["opening_stock"]), "received_at":master["opening_date"] or "1900-01-01"})
    rows = db.execute("SELECT gl.lot_no, SUM(gl.quantity) received, MIN(ge.grn_date) received_at FROM grn_lines gl JOIN grn_entries ge ON ge.id=gl.grn_id WHERE gl.material_kind=? AND gl.master_id=? AND gl.plant=? GROUP BY gl.lot_no ORDER BY received_at, gl.id", (kind, master_id, plant)).fetchall()
    for r in rows:
        issued = db.execute("SELECT COALESCE(SUM(la.quantity),0) FROM lot_issue_allocations la JOIN material_issue_transactions it ON it.id=la.issue_transaction_id WHERE it.material_kind=? AND it.master_id=? AND it.plant=? AND la.lot_no=?", (kind, master_id, plant, r["lot_no"])).fetchone()[0]
        lots.append({"lot_no":r["lot_no"], "received":float(r["received"] or 0), "issued":float(issued or 0), "balance":max(0,float(r["received"] or 0)-float(issued or 0)), "received_at":r["received_at"] or ""})
    return [x for x in lots if x["balance"] > 0]


def material_label(row, kind):
    if kind == "RAW":
        return row["rm_name"]
    if kind == "POLY BAG":
        return row["poly_bag_size"]
    return row["description"]


@app.route("/requisitions")
@login_required
def requisitions():
    scope, params = plant_scope("r")
    with connect_db() as db:
        rows = db.execute(f"SELECT r.*, (SELECT COUNT(*) FROM requisition_lines l WHERE l.requisition_id=r.id) AS line_count FROM requisitions r WHERE {scope} ORDER BY r.id DESC LIMIT 250", params).fetchall()
    return render_template("requisitions.html", rows=rows)


@app.route("/requisitions/new", methods=["GET", "POST"])
@login_required
def requisition_new():
    allowed_plants = ("J BLOCK", "F-2 BLOCK", "T BLOCK", "S BLOCK")
    target_plant = request.form.get("plant", session.get("plant", "J BLOCK")) if request.method == "POST" else request.args.get("plant", ("J BLOCK" if session.get("role") == "admin" else session.get("plant", "J BLOCK")))
    if session.get("role") != "admin":
        target_plant = session.get("plant", "J BLOCK")
    if target_plant not in allowed_plants:
        target_plant = "J BLOCK"
    with connect_db() as db:
        materials = []
        for kind, (table, name_col) in MATERIAL_MASTER_TABLES.items():
            rows = db.execute(f"SELECT * FROM {table} WHERE plant=? ORDER BY {name_col}", (target_plant,)).fetchall()
            for row in rows:
                stock_qty = material_current_stock(db, kind, row["id"], target_plant)
                materials.append({"key": f"{kind}|{row['id']}", "kind": kind, "id": row["id"], "name": material_label(row, kind),
                                  "grade": row["rm_grade"] if kind == "RAW" else "", "color": row["color"] if kind == "RAW" else "",
                                  "party": row["party_name"] or "", "stock": stock_qty or 0})
        if request.method == "POST":
            mold_no = request.form.get("mold_no", "").strip()
            machine_no = request.form.get("machine_no", "").strip()
            supervisor = request.form.get("supervisor", "").strip()
            notes = request.form.get("notes", "").strip()
            chosen_keys = request.form.getlist("material_key[]")
            quantities = request.form.getlist("requested_qty[]")
            if not mold_no or not machine_no or not supervisor:
                flash("Mold No., Machine No. आणि Supervisor नाव आवश्यक आहे. / Complete the production details.", "error")
            else:
                line_data = []
                try:
                    for key, qty_text in zip(chosen_keys, quantities):
                        if not key:
                            continue
                        kind, id_text = key.split("|", 1)
                        if kind not in MATERIAL_MASTER_TABLES:
                            raise ValueError()
                        qty = float(qty_text or 0)
                        if qty <= 0:
                            raise ValueError()
                        master_id = int(id_text)
                        table, _ = MATERIAL_MASTER_TABLES[kind]
                        row = db.execute(f"SELECT * FROM {table} WHERE id=? AND plant=?", (master_id, target_plant)).fetchone()
                        if not row:
                            raise ValueError()
                        current = material_current_stock(db, kind, master_id, target_plant) or 0
                        line_data.append((kind, master_id, material_label(row, kind), row["rm_grade"] if kind == "RAW" else "", row["color"] if kind == "RAW" else "", row["party_name"] or "", qty, current))
                    if not line_data:
                        raise ValueError()
                except (ValueError, TypeError):
                    flash("किमान एक Material निवडा आणि योग्य Quantity भरा. / Select material(s) and enter valid quantities.", "error")
                else:
                    shortage = any(qty > stock for _, _, _, _, _, _, qty, stock in line_data)
                    status = "DRAFT" if shortage else "PENDING_STORE"
                    req_no = "MR-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")[-18:]
                    now = datetime.now().isoformat(timespec="seconds")
                    cur = db.execute("INSERT INTO requisitions(requisition_no,plant,mold_no,machine_no,supervisor,requested_by,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                     (req_no, target_plant, mold_no, machine_no, supervisor, session["user"], status, notes, now))
                    req_id = cur.lastrowid
                    for kind, master_id, name, grade, color, party, qty, stock_qty in line_data:
                        db.execute("INSERT INTO requisition_lines(requisition_id,material_kind,master_id,material_name,grade,color,party_name,requested_qty,available_at_request,plant) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                   (req_id, kind, master_id, name, grade, color, party, qty, stock_qty, target_plant))
                    if shortage:
                        flash(f"Requisition {req_no} Draft मध्ये सेव्ह झाली. काही Material चा Stock कमी आहे; Stock तपासून पुन्हा submit करावा. / Saved as Draft due to shortage.", "success")
                    else:
                        flash(f"Requisition {req_no} Store कडे पाठवली. / Sent to Store.", "success")
                    return redirect(url_for("requisitions"))
    return render_template("requisition_form.html", materials=materials, target_plant=target_plant, plants=allowed_plants)


@app.route("/requisitions/<int:req_id>")
@login_required
def requisition_detail(req_id):
    scope, params = plant_scope("r")
    with connect_db() as db:
        req = db.execute(f"SELECT r.* FROM requisitions r WHERE r.id=? AND {scope}", (req_id, *params)).fetchone()
        if not req:
            flash("Requisition सापडली नाही. / Requisition not found.", "error")
            return redirect(url_for("requisitions"))
        raw_lines = db.execute("SELECT * FROM requisition_lines WHERE requisition_id=? ORDER BY id", (req_id,)).fetchall()
        lines = []
        for line in raw_lines:
            item = dict(line)
            item["current_stock"] = material_current_stock(db, line["material_kind"], line["master_id"], line["plant"]) or 0
            item["lots"] = lot_stock_rows(db, line["material_kind"], line["master_id"], line["plant"])
            lines.append(item)
    return render_template("requisition_detail.html", req=req, lines=lines)


@app.route("/requisitions/<int:req_id>/submit", methods=["POST"])
@login_required
def requisition_submit(req_id):
    scope, params = plant_scope("r")
    with connect_db() as db:
        req = db.execute(f"SELECT r.* FROM requisitions r WHERE r.id=? AND {scope}", (req_id, *params)).fetchone()
        if not req:
            flash("Requisition सापडली नाही. / Requisition not found.", "error")
            return redirect(url_for("requisitions"))
        if req["status"] != "DRAFT":
            flash("फक्त Draft Requisition पुन्हा Submit करता येते. / Only drafts can be resubmitted.", "error")
            return redirect(url_for("requisition_detail", req_id=req_id))
        lines = db.execute("SELECT * FROM requisition_lines WHERE requisition_id=?", (req_id,)).fetchall()
        insufficient = []
        for line in lines:
            current = material_current_stock(db, line["material_kind"], line["master_id"], line["plant"]) or 0
            if current < float(line["requested_qty"]):
                insufficient.append(line["material_name"])
        if insufficient:
            flash("अजून पुरेसा Stock उपलब्ध नाही: " + ", ".join(insufficient), "error")
        else:
            db.execute("UPDATE requisitions SET status='PENDING_STORE' WHERE id=?", (req_id,))
            flash("Stock उपलब्ध आहे. Requisition Store कडे पाठवली. / Sent to Store.", "success")
    return redirect(url_for("requisition_detail", req_id=req_id))


@app.route("/requisitions/<int:req_id>/finalize", methods=["POST"])
@login_required
def requisition_finalize(req_id):
    if session.get("role") != "admin" and session.get("plant") not in ("ADMIN",):
        # Plant users may perform Store finalization for their own plant.
        pass
    with connect_db() as db:
        scope, params = plant_scope("r")
        req = db.execute(f"SELECT r.* FROM requisitions r WHERE r.id=? AND {scope}", (req_id, *params)).fetchone()
        if not req:
            flash("Requisition सापडली नाही. / Requisition not found.", "error")
            return redirect(url_for("requisitions"))
        if req["status"] == "FINAL":
            flash("ही Requisition आधीच Final झाली आहे. / Already finalized.", "error")
            return redirect(url_for("requisition_detail", req_id=req_id))
        if req["status"] != "PENDING_STORE":
            flash("Stock shortage Draft Store कडून Final करता येणार नाही. Stock उपलब्ध झाल्यावर Recheck & Send Store करा. / Draft cannot be finalized until stock is available.", "error")
            return redirect(url_for("requisition_detail", req_id=req_id))
        lines = db.execute("SELECT * FROM requisition_lines WHERE requisition_id=? ORDER BY id", (req_id,)).fetchall()
        issued_values = []
        shortage = False
        try:
            for line in lines:
                issued = float(request.form.get(f"issued_{line['id']}", "0") or 0)
                current = material_current_stock(db, line["material_kind"], line["master_id"], line["plant"])
                mode = request.form.get(f"mode_{line['id']}", "manual").lower()
                selected_lot = request.form.get(f"lot_{line['id']}", "")
                if issued < 0 or issued > float(line["requested_qty"]) or current is None or issued > current or mode not in ("manual", "fifo"):
                    raise ValueError()
                allocations=[]
                lots=lot_stock_rows(db,line["material_kind"],line["master_id"],line["plant"])
                if issued > 0:
                    if mode == "manual":
                        lot=next((x for x in lots if x["lot_no"]==selected_lot),None)
                        if not lot or issued > lot["balance"]: raise ValueError()
                        allocations=[(lot["lot_no"],issued)]
                    else:
                        remaining=issued
                        for lot in sorted(lots,key=lambda x:x["received_at"]):
                            take=min(remaining,lot["balance"])
                            if take>0: allocations.append((lot["lot_no"],take)); remaining-=take
                            if remaining<=0: break
                        if remaining>0: raise ValueError()
                if issued < float(line["requested_qty"]): shortage = True
                issued_values.append((line, issued, allocations))
        except (ValueError, TypeError):
            flash("Issue Quantity उपलब्ध Stock पेक्षा किंवा मागणीपेक्षा जास्त असू शकत नाही. / Check issue quantities and current stock.", "error")
            return redirect(url_for("requisition_detail", req_id=req_id))
        if shortage and not any(qty > 0 for _, qty, _ in issued_values):
            flash("किमान एक Material ची Issue Quantity द्या. / Enter at least one issue quantity.", "error")
            return redirect(url_for("requisition_detail", req_id=req_id))
        now = datetime.now().isoformat(timespec="seconds")
        for line, issued, allocations in issued_values:
            db.execute("UPDATE requisition_lines SET issued_qty=? WHERE id=?", (issued, line["id"]))
            if issued > 0:
                cur=db.execute("INSERT INTO material_issue_transactions(requisition_id,requisition_line_id,material_kind,master_id,quantity,plant,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                           (req_id, line["id"], line["material_kind"], line["master_id"], issued, line["plant"], session["user"], now))
                for lot_no, lot_qty in allocations:
                    db.execute("INSERT INTO lot_issue_allocations(issue_transaction_id,lot_no,quantity) VALUES(?,?,?)",(cur.lastrowid,lot_no,lot_qty))
        db.execute("UPDATE requisitions SET status='FINAL',store_by=?,finalized_at=? WHERE id=?", (session["user"], now, req_id))
    flash("Store Issue Final Save झाली. Stock अपडेट झाला. / Final issue saved and stock updated.", "success")
    return redirect(url_for("requisition_detail", req_id=req_id))



@app.route("/grn", methods=["GET", "POST"])
@login_required
def grn():
    kind = request.values.get("kind", "RAW")
    if kind not in MATERIAL_MASTER_TABLES: kind = "RAW"
    scope, params = plant_scope()
    with connect_db() as db:
        materials = []
        for k, (table, name_col) in MATERIAL_MASTER_TABLES.items():
            rows = db.execute(f"SELECT id, {name_col} AS name FROM {table} WHERE {scope} ORDER BY {name_col}", params).fetchall()
            materials.extend([{"id":r["id"],"name":r["name"],"kind":k} for r in rows])
        if request.method == "POST":
            party=request.form.get("party_name", "").strip(); invoice=request.form.get("invoice_no", "").strip(); invoice_date=request.form.get("invoice_date", ""); grn_date=request.form.get("grn_date", "") or datetime.now().date().isoformat()
            try:
                ids=request.form.getlist("material_id[]"); lots=request.form.getlist("lot_no[]"); qtys=request.form.getlist("quantity[]"); packings=request.form.getlist("packing[]")
                lines=[]
                for mid, lot, qty, packing in zip(ids,lots,qtys,packings):
                    q=float(qty or 0)
                    if not mid and not lot and q==0: continue
                    if not mid or not lot.strip() or q<=0: raise ValueError()
                    lines.append((int(mid),lot.strip(),q,packing.strip()))
                if not party or not invoice or not invoice_date or not lines: raise ValueError()
            except (ValueError, TypeError):
                flash("Party, Invoice, Invoice Date आणि प्रत्येक LOT साठी Material, LOT No. व positive Qty आवश्यक आहे.", "error")
                return redirect(url_for("grn", kind=kind))
            target_plant=session.get("plant", "ADMIN")
            now=datetime.now().isoformat(timespec="seconds")
            grn_no="GRN-"+datetime.now().strftime("%Y%m%d%H%M%S%f")
            cur=db.execute("INSERT INTO grn_entries(grn_no,material_kind,party_name,invoice_no,invoice_date,vehicle_no,po_no,grn_date,saved_at,created_by,tc_received,eway_received,plant) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (grn_no,kind,party,invoice,invoice_date,request.form.get("vehicle_no",""),request.form.get("po_no",""),grn_date,now,session.get("user",""),1 if request.form.get("tc_received") else 0,1 if request.form.get("eway_received") else 0,target_plant))
            for mid,lot,q,packing in lines:
                table,_=MATERIAL_MASTER_TABLES[kind]
                if not db.execute(f"SELECT id FROM {table} WHERE id=? AND plant=?",(mid,target_plant)).fetchone():
                    raise ValueError("Selected material is not in your plant")
                db.execute("INSERT INTO grn_lines(grn_id,material_kind,master_id,lot_no,quantity,packing,plant) VALUES(?,?,?,?,?,?,?)",(cur.lastrowid,kind,mid,lot,q,packing,target_plant))
            flash(f"GRN {grn_no} सेव्ह झाली. LOT-wise Stock अपडेट झाला.", "success")
            return redirect(url_for("grn"))
        entries=db.execute(f"SELECT * FROM grn_entries WHERE {scope} ORDER BY id DESC LIMIT 100",params).fetchall()
    return render_template("grn.html", materials=materials, entries=entries, selected_kind=kind, today=datetime.now().date().isoformat(), now=datetime.now().strftime("%H:%M:%S"))


@app.route("/lot-stock")
@login_required
def lot_stock_report():
    scope, params=plant_scope()
    reports=[]
    with connect_db() as db:
        for kind,(table,name_col) in MATERIAL_MASTER_TABLES.items():
            rows=db.execute(f"SELECT * FROM {table} WHERE {scope} ORDER BY {name_col}",params).fetchall()
            for r in rows:
                total=material_current_stock(db,kind,r["id"],r["plant"]) or 0
                lots=lot_stock_rows(db,kind,r["id"],r["plant"])
                minq=float(r["min_qty"] or 0); maxq=float(r["max_qty"] or 0)
                status="LOW" if total<minq else ("MIN LEVEL" if total==minq else ("OVER MAX" if total>maxq else ("MAX LEVEL" if total==maxq else "OK")))
                reports.append({"kind":kind,"name":material_label(r,kind),"plant":r["plant"],"min":minq,"max":maxq,"total":total,"status":status,"lots":lots})
    return render_template("lot_stock.html", reports=reports)


@app.route("/backup")
@login_required
def backup():
    """Admin downloads the full database; plant users get a JSON export of their plant records."""
    from flask import send_file
    if session.get("role") == "admin":
        if not os.path.exists(DB_PATH):
            flash("Backup साठी database सापडला नाही.", "error")
            return redirect(url_for("dashboard"))
        return send_file(DB_PATH, as_attachment=True, download_name="DIVINE_STORE_ALL_PLANTS_BACKUP_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db", mimetype="application/octet-stream")
    plant = session.get("plant", "ADMIN")
    export = {"application": APP_NAME, "plant": plant, "created_at": datetime.now().isoformat(timespec="seconds"), "tables": {}}
    plant_tables = ("items", "stock_transactions", "raw_material_master", "poly_bag_master", "bop_master", "requisitions", "requisition_lines", "material_issue_transactions", "grn_entries", "grn_lines")
    with connect_db() as db:
        for table in plant_tables:
            exists = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                continue
            cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]
            if "plant" in cols:
                rows = db.execute(f"SELECT * FROM {table} WHERE plant=?", (plant,)).fetchall()
            else:
                rows = []
            export["tables"][table] = [dict(r) for r in rows]
    data = io.BytesIO(json.dumps(export, ensure_ascii=False, indent=2, default=str).encode("utf-8"))
    data.seek(0)
    return send_file(data, as_attachment=True, download_name="DIVINE_STORE_" + plant.replace(" ", "_") + "_BACKUP_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json", mimetype="application/json")

@app.route("/health")
def health():
    return {"status":"ok","app":APP_NAME}


# ---------- Store-specific masters ----------
MASTER_CONFIG = {
    "raw-material": {
        "title": "RAW MATERIAL MASTER",
        "table": "raw_material_master",
        "fields": [
            ("rm_name", "RM NAME", "text", True),
            ("rm_grade", "RM GRADE", "text", False),
            ("color", "COLOR", "text", False),
            ("hsn", "H.S.N", "text", False),
            ("party_name", "PARTY NAME", "text", False),
            ("min_qty", "Min", "number", False),
            ("max_qty", "Max", "number", False),
            ("opening_stock", "OPENING STOCK", "number", False),
            ("opening_date", "OPENING STOCK DATE", "date", False),
        ],
    },
    "poly-bag": {
        "title": "POLY BAG MASTER",
        "table": "poly_bag_master",
        "fields": [
            ("poly_bag_size", "POLY BAG SIZE", "text", True),
            ("party_name", "PARTY NAME", "text", False),
            ("hsn", "H.S.N", "text", False),
            ("min_qty", "Min", "number", False),
            ("max_qty", "Max", "number", False),
            ("opening_stock", "OPENING STOCK", "number", False),
            ("opening_date", "OPENING STOCK DATE", "date", False),
        ],
    },
    "bop": {
        "title": "BOP MASTER",
        "table": "bop_master",
        "fields": [
            ("description", "DESCRIPTION", "text", True),
            ("party_name", "PARTY NAME", "text", False),
            ("min_qty", "Min", "number", False),
            ("max_qty", "Max", "number", False),
            ("opening_stock", "OPENING STOCK", "number", False),
            ("opening_date", "OPENING STOCK DATE", "date", False),
        ],
    },
}

def master_columns(kind):
    return MASTER_CONFIG[kind]["fields"]

@app.route("/masters/<kind>")
@login_required
def store_master(kind):
    config = MASTER_CONFIG.get(kind)
    if not config:
        flash("Master सापडला नाही. / Master not found.", "error")
        return redirect(url_for("dashboard"))
    q = request.args.get("q", "").strip()
    searchable = [field[0] for field in config["fields"] if field[2] == "text"]
    where = " OR ".join(f"{col} LIKE ?" for col in searchable) or "1=1"
    args = [f"%{q}%"] * len(searchable)
    scope, scope_params = plant_scope()
    with connect_db() as db:
        rows = db.execute(f"SELECT * FROM {config['table']} WHERE ({scope}) AND ({where}) ORDER BY id DESC", scope_params + args).fetchall()
    return render_template("master_list.html", kind=kind, config=config, rows=rows, q=q)

@app.route("/masters/<kind>/new", methods=["GET", "POST"])
@login_required
def store_master_new(kind):
    config = MASTER_CONFIG.get(kind)
    if not config:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        data = {}
        for key, label, field_type, required in config["fields"]:
            value = request.form.get(key, "").strip()
            if required and not value:
                flash(f"{label} आवश्यक आहे. / {label} is required.", "error")
                return render_template("master_form.html", kind=kind, config=config, row=request.form, editing=False)
            if field_type == "number":
                try:
                    value = float(value or 0)
                    if value < 0:
                        raise ValueError()
                except ValueError:
                    flash(f"{label}: शून्य किंवा सकारात्मक संख्या द्या. / Enter a non-negative number.", "error")
                    return render_template("master_form.html", kind=kind, config=config, row=request.form, editing=False)
            data[key] = value
        keys = list(data.keys())
        placeholders = ",".join("?" for _ in keys)
        target_plant = request.form.get("plant", session.get("plant", "ADMIN")) if session.get("role") == "admin" else session.get("plant", "ADMIN")
        if target_plant not in ("ADMIN", "J BLOCK", "F-2 BLOCK", "T BLOCK", "S BLOCK"):
            target_plant = session.get("plant", "ADMIN")
        columns = ",".join(keys + ["plant", "created_at"])
        placeholders = placeholders + ",?,?"
        with connect_db() as db:
            db.execute(f"INSERT INTO {config['table']} ({columns}) VALUES ({placeholders})",
                       [data[k] for k in keys] + [target_plant, datetime.now().isoformat(timespec="seconds")])
        flash(f"{config['title']} मध्ये नोंद सेव्ह झाली. / Record saved.", "success")
        return redirect(url_for("store_master", kind=kind))
    return render_template("master_form.html", kind=kind, config=config, row={}, editing=False)

@app.route("/masters/<kind>/<int:row_id>/edit", methods=["GET", "POST"])
@login_required
def store_master_edit(kind, row_id):
    config = MASTER_CONFIG.get(kind)
    if not config:
        return redirect(url_for("dashboard"))
    with connect_db() as db:
        scope, scope_params = plant_scope()
        row = db.execute(f"SELECT * FROM {config['table']} WHERE id=? AND {scope}", (row_id, *scope_params)).fetchone()
        if not row:
            flash("नोंद सापडली नाही. / Record not found.", "error")
            return redirect(url_for("store_master", kind=kind))
        if request.method == "POST":
            data = {}
            for key, label, field_type, required in config["fields"]:
                value = request.form.get(key, "").strip()
                if required and not value:
                    flash(f"{label} आवश्यक आहे. / {label} is required.", "error")
                    return render_template("master_form.html", kind=kind, config=config, row=request.form, editing=True)
                if field_type == "number":
                    try:
                        value = float(value or 0)
                        if value < 0: raise ValueError()
                    except ValueError:
                        flash(f"{label}: शून्य किंवा सकारात्मक संख्या द्या. / Enter a non-negative number.", "error")
                        return render_template("master_form.html", kind=kind, config=config, row=request.form, editing=True)
                data[key] = value
            updates = ",".join(f"{k}=?" for k in data)
            db.execute(f"UPDATE {config['table']} SET {updates} WHERE id=? AND plant=?", list(data.values()) + [row_id, row["plant"]])
            flash("नोंद अपडेट झाली. / Record updated.", "success")
            return redirect(url_for("store_master", kind=kind))
    return render_template("master_form.html", kind=kind, config=config, row=dict(row), editing=True)

init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
