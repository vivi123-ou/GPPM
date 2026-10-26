"""Demo Shop phone store API and embedded storefront for TestPilot demos."""
import json
import os
import hashlib
import hmac
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

router = APIRouter(tags=["Demo Shop"])
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DB_PATH = Path(os.getenv("DEMO_SHOP_DB", Path(__file__).resolve().parents[1] / "demo_shop.db"))
SESSION_COOKIE = "tvt_shop_session"
SESSION_MAX_AGE = 7 * 24 * 60 * 60
PASSWORD_ITERATIONS = 310_000

PRODUCTS = [
    ("iphone-15", "iPhone 15", "Apple", 19990000, 18, "6.1\" OLED · 128 GB · 48 MP", "📱", "#e8e8f0"),
    ("galaxy-s24", "Galaxy S24", "Samsung", 18990000, 15, "6.2\" AMOLED · 256 GB · Galaxy AI", "📱", "#e5edff"),
    ("pixel-8", "Pixel 8", "Google", 14990000, 9, "6.2\" OLED · 128 GB · Camera AI", "📱", "#e6f3ea"),
    ("xiaomi-14", "Xiaomi 14", "Xiaomi", 16990000, 12, "6.36\" AMOLED · 256 GB · Leica", "📱", "#fff0e5"),
    ("iphone-16-pro", "iPhone 16 Pro", "Apple", 28990000, 8, "6.3\" OLED · 256 GB · Camera Control", "📱", "#eeeae2"),
    ("galaxy-z-flip6", "Galaxy Z Flip6", "Samsung", 24990000, 7, "6.7\" Foldable AMOLED · 256 GB · Galaxy AI", "📱", "#e5eafa"),
    ("redmi-note-14-pro", "Redmi Note 14 Pro", "Xiaomi", 7990000, 20, "6.67\" AMOLED · 256 GB · 200 MP", "📱", "#f4e8e4"),
    ("oppo-reno13", "OPPO Reno13", "OPPO", 13990000, 11, "6.59\" AMOLED · 256 GB · AI Portrait", "📱", "#e4eff0"),
]

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_shop_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS products(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL,
          price INTEGER NOT NULL CHECK(price >= 0), stock INTEGER NOT NULL CHECK(stock >= 0),
          description TEXT NOT NULL, emoji TEXT NOT NULL, color TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(
          id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL,
          email TEXT NOT NULL, address TEXT NOT NULL, total INTEGER NOT NULL,
          items_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          phone TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
          payment_method TEXT NOT NULL DEFAULT 'cod', note TEXT NOT NULL DEFAULT '',
          user_id INTEGER REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS bug_flags(
          name TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE, password_salt TEXT NOT NULL,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS auth_sessions(
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)
        order_columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
        for name, sql_type in (
            ("phone", "TEXT NOT NULL DEFAULT ''"),
            ("city", "TEXT NOT NULL DEFAULT ''"),
            ("payment_method", "TEXT NOT NULL DEFAULT 'cod'"),
            ("note", "TEXT NOT NULL DEFAULT ''"),
            ("user_id", "INTEGER REFERENCES users(id)"),
        ):
            if name not in order_columns:
                conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {sql_type}")
        for p in PRODUCTS:
            conn.execute("INSERT OR IGNORE INTO products VALUES(?,?,?,?,?,?,?,?)", p)
        for flag in ("wrong_total", "allow_empty_email", "ignore_stock", "ui_v2"):
            conn.execute("INSERT OR IGNORE INTO bug_flags(name, enabled) VALUES(?, 0)", (flag,))
        seed_email = os.getenv("SHOP_DEMO_EMAIL", "").strip().lower()
        seed_password = os.getenv("SHOP_DEMO_PASSWORD", "")
        if seed_email and seed_password and not conn.execute(
            "SELECT 1 FROM users WHERE email=?", (seed_email,)
        ).fetchone():
            salt, password_hash = _hash_password(seed_password)
            conn.execute(
                "INSERT INTO users(name,email,password_salt,password_hash) VALUES(?,?,?,?)",
                ("Trinh", seed_email, salt, password_hash),
            )


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return salt.hex(), digest.hex()


def _valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email))


def _session_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as conn:
        row = conn.execute(
            "SELECT u.id,u.name,u.email FROM auth_sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.created_at > datetime('now','-7 days')",
            (token_hash,),
        ).fetchone()
        return dict(row) if row else None


def _new_session(user_id: int, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as conn:
        conn.execute("INSERT INTO auth_sessions(token_hash,user_id) VALUES(?,?)", (token_hash, user_id))
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True,
        secure=os.getenv("COOKIE_SECURE", "0") == "1", samesite="lax", path="/",
    )


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


@router.post("/api/shop/auth/register", status_code=201)
def register(body: RegisterIn, response: Response):
    init_shop_db()
    email = body.email.strip().lower()
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Vui lòng nhập họ tên")
    if not _valid_email(email):
        raise HTTPException(422, "Email không hợp lệ")
    salt, password_hash = _hash_password(body.password)
    try:
        with connect() as conn:
            user_id = conn.execute(
                "INSERT INTO users(name,email,password_salt,password_hash) VALUES(?,?,?,?)",
                (name, email, salt, password_hash),
            ).lastrowid
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Email này đã được đăng ký") from exc
    _new_session(user_id, response)
    return {"id": user_id, "name": name, "email": email}


@router.post("/api/shop/auth/login")
def login(body: LoginIn, response: Response):
    init_shop_db()
    email = body.email.strip().lower()
    with connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user:
        raise HTTPException(401, "Email hoặc mật khẩu chưa đúng")
    _, candidate = _hash_password(body.password, bytes.fromhex(user["password_salt"]))
    if not hmac.compare_digest(candidate, user["password_hash"]):
        raise HTTPException(401, "Email hoặc mật khẩu chưa đúng")
    _new_session(user["id"], response)
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


@router.get("/api/shop/auth/me")
def current_user(request: Request):
    init_shop_db()
    user = _session_user(request)
    if not user:
        raise HTTPException(401, "Bạn cần đăng nhập")
    return user


@router.post("/api/shop/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with connect() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return {"ok": True}

@router.get("/shop", response_class=HTMLResponse, include_in_schema=False)
def shop_page():
    init_shop_db()
    return HTMLResponse((Path(__file__).parent / "templates" / "shop.html").read_text(encoding="utf-8"))

@router.get("/shop/about", response_class=HTMLResponse, include_in_schema=False)
def shop_about_page():
    return HTMLResponse((Path(__file__).parent / "templates" / "about.html").read_text(encoding="utf-8"))

@router.get("/shop/login", response_class=HTMLResponse, include_in_schema=False)
def shop_login_page():
    init_shop_db()
    return HTMLResponse((Path(__file__).parent / "templates" / "login.html").read_text(encoding="utf-8"))

@router.get("/shop/register", response_class=HTMLResponse, include_in_schema=False)
def shop_register_page():
    init_shop_db()
    return HTMLResponse((Path(__file__).parent / "templates" / "register.html").read_text(encoding="utf-8"))

@router.get("/api/shop/products")
def list_products():
    init_shop_db()
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM products ORDER BY name")]

class CheckoutItem(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=20)

class CheckoutIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    address: str = Field(min_length=5, max_length=300)
    phone: str = Field(default="", max_length=30)
    city: str = Field(default="", max_length=100)
    payment_method: str = Field(default="cod", max_length=30)
    note: str = Field(default="", max_length=500)
    items: list[CheckoutItem] = Field(min_length=1)

@router.post("/api/shop/checkout", status_code=201)
def checkout(body: CheckoutIn, request: Request):
    init_shop_db()
    user = _session_user(request)
    if not user:
        raise HTTPException(401, "Bạn cần đăng nhập trước khi đặt hàng")
    with connect() as conn:
        flags = {r["name"]: bool(r["enabled"]) for r in conn.execute("SELECT * FROM bug_flags")}
        if not flags.get("allow_empty_email") and ("@" not in body.email or "." not in body.email.rsplit("@", 1)[-1]):
            raise HTTPException(422, "Email không hợp lệ")
        total = 0
        items = []
        for item in body.items:
            row = conn.execute("SELECT * FROM products WHERE id=?", (item.product_id,)).fetchone()
            if row is None:
                raise HTTPException(404, f"Không tìm thấy sản phẩm: {item.product_id}")
            if not flags.get("ignore_stock") and row["stock"] < item.quantity:
                raise HTTPException(409, f"{row['name']} không đủ hàng")
            subtotal = row["price"] * item.quantity
            total += subtotal
            items.append({"product_id": row["id"], "name": row["name"], "unit_price": row["price"],
                          "quantity": item.quantity, "subtotal": subtotal})
        reported_total = total + 100000 if flags.get("wrong_total") else total
        cur = conn.execute(
            "INSERT INTO orders(customer_name,email,address,total,items_json,phone,city,payment_method,note,user_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (body.customer_name, body.email, body.address, reported_total,
             json.dumps(items, ensure_ascii=False), body.phone, body.city,
             body.payment_method, body.note, user["id"]),
        )
        if not flags.get("ignore_stock"):
            for item in body.items:
                conn.execute("UPDATE products SET stock=stock-? WHERE id=?", (item.quantity, item.product_id))
        return {"order_id": cur.lastrowid, "total": reported_total, "items": items, "message": "Đặt hàng thành công"}

@router.get("/api/shop/orders/{order_id}")
def get_order(order_id: int):
    init_shop_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Không tìm thấy đơn hàng")
        order = dict(row)
        order["items"] = json.loads(order.pop("items_json"))
        return order

@router.get("/api/shop/bugs")
def get_bug_flags():
    init_shop_db()
    with connect() as conn:
        return {r["name"]: bool(r["enabled"]) for r in conn.execute("SELECT * FROM bug_flags")}

class BugFlagIn(BaseModel):
    enabled: bool

@router.put("/api/shop/bugs/{flag}")
def set_bug_flag(flag: str, body: BugFlagIn):
    init_shop_db()
    with connect() as conn:
        cur = conn.execute("UPDATE bug_flags SET enabled=? WHERE name=?", (int(body.enabled), flag))
        if cur.rowcount == 0:
            raise HTTPException(404, "Bug flag không tồn tại")
    return {"name": flag, "enabled": body.enabled}

@router.post("/api/shop/reset")
def reset_shop():
    init_shop_db()
    with connect() as conn:
        conn.execute("DELETE FROM orders")
        for product in PRODUCTS:
            conn.execute("UPDATE products SET stock=? WHERE id=?", (product[4], product[0]))
        conn.execute("UPDATE bug_flags SET enabled=0")
    return {"ok": True, "message": "Demo Shop đã được đặt lại"}
