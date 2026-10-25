"""Demo Shop phone store API and embedded storefront for TestPilot demos."""
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

router = APIRouter(tags=["Demo Shop"])
DB_PATH = Path(os.getenv("DEMO_SHOP_DB", Path(__file__).resolve().parents[1] / "demo_shop.db"))

PRODUCTS = [
    ("iphone-15", "iPhone 15", "Apple", 19990000, 18, "6.1\" OLED · 128 GB · 48 MP", "📱", "#e8e8f0"),
    ("galaxy-s24", "Galaxy S24", "Samsung", 18990000, 15, "6.2\" AMOLED · 256 GB · Galaxy AI", "📱", "#e5edff"),
    ("pixel-8", "Pixel 8", "Google", 14990000, 9, "6.2\" OLED · 128 GB · Camera AI", "📱", "#e6f3ea"),
    ("xiaomi-14", "Xiaomi 14", "Xiaomi", 16990000, 12, "6.36\" AMOLED · 256 GB · Leica", "📱", "#fff0e5"),
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
          payment_method TEXT NOT NULL DEFAULT 'cod', note TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS bug_flags(
          name TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0);
        """)
        order_columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
        for name, sql_type in (
            ("phone", "TEXT NOT NULL DEFAULT ''"),
            ("city", "TEXT NOT NULL DEFAULT ''"),
            ("payment_method", "TEXT NOT NULL DEFAULT 'cod'"),
            ("note", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in order_columns:
                conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {sql_type}")
        for p in PRODUCTS:
            conn.execute("INSERT OR IGNORE INTO products VALUES(?,?,?,?,?,?,?,?)", p)
        for flag in ("wrong_total", "allow_empty_email", "ignore_stock", "ui_v2"):
            conn.execute("INSERT OR IGNORE INTO bug_flags(name, enabled) VALUES(?, 0)", (flag,))

@router.get("/shop", response_class=HTMLResponse, include_in_schema=False)
def shop_page():
    init_shop_db()
    return HTMLResponse((Path(__file__).parent / "templates" / "shop.html").read_text(encoding="utf-8"))

@router.get("/shop/about", response_class=HTMLResponse, include_in_schema=False)
def shop_about_page():
    return HTMLResponse((Path(__file__).parent / "templates" / "about.html").read_text(encoding="utf-8"))

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
def checkout(body: CheckoutIn):
    init_shop_db()
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
            "INSERT INTO orders(customer_name,email,address,total,items_json,phone,city,payment_method,note) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (body.customer_name, body.email, body.address, reported_total,
             json.dumps(items, ensure_ascii=False), body.phone, body.city,
             body.payment_method, body.note),
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
        conn.execute("UPDATE products SET stock=CASE id WHEN 'iphone-15' THEN 18 WHEN 'galaxy-s24' THEN 15 WHEN 'pixel-8' THEN 9 WHEN 'xiaomi-14' THEN 12 END")
        conn.execute("UPDATE bug_flags SET enabled=0")
    return {"ok": True, "message": "Demo Shop đã được đặt lại"}
