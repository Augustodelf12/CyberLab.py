#!/usr/bin/env python3
"""
TechVerse Shop — loja web REALISTA e intencionalmente vulnerável (nível médio).

Roda apenas na rede isolada do CyberLab.

Vulnerabilidades plantadas:
  /search?q=              -> SQL injection (UNION-based)
  /login                  -> SQLi auth bypass + session fixation
  /orders/<id>            -> IDOR (acessar pedidos de outros)
  /feedback               -> XSS armazenado
  /api/status?url=        -> SSRF (requisição a URL interna/externa)
  /tools/ping?host=       -> command injection com blacklist falha
  /admin                  -> broken access control (flag parcial)

Objetivo final: ler /flag.txt (via command injection).
"""
import os
import re
import sqlite3
import subprocess
import urllib.request
from functools import wraps

from flask import Flask, abort, redirect, render_template_string, request, session

app = Flask(__name__)
app.secret_key = "nao-e-tao-secreto-assim"

DB = "/tmp/shop.db"
FLAG = "/flag.txt"


def init_db() -> None:
    if os.path.exists(DB):
        return
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT)")
    db.execute("CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, price REAL, desc TEXT)")
    db.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, user_id INTEGER, item TEXT, total REAL)")
    db.execute("CREATE TABLE feedback(id INTEGER PRIMARY KEY, user TEXT, msg TEXT)")
    db.executemany(
        "INSERT INTO users(username, password, role) VALUES(?,?,?)",
        [("admin", "T3chV3rse_Admin!99", "admin"), ("alice", "alice123", "user"), ("bob", "letmein", "user")],
    )
    db.executemany(
        "INSERT INTO products(name, price, desc) VALUES(?,?,?)",
        [
            ("Roteador Quantum", 299.90, "Wi-Fi 7 de última geração"),
            ("SSD 2TB NVMe", 899.00, "Leitura de 7000 MB/s"),
            ("Teclado Mecânico RGB", 349.90, "Switches hot-swappable"),
            ("Monitor 4K 27\"", 1899.00, "144Hz, 1ms, IPS"),
            ("Webcam 4K", 499.90, "Foco automático por IA"),
        ],
    )
    db.executemany(
        "INSERT INTO orders(user_id, item, total) VALUES(?,?,?)",
        [(1, "SSD 2TB NVMe", 899.00), (2, "Webcam 4K", 499.90), (1, "Roteador Quantum", 299.90)],
    )
    db.execute("INSERT INTO feedback(user, msg) VALUES('admin','Bem-vindos à TechVerse! Novidades em breve.')")
    db.commit()
    db.close()


init_db()

BASE = """<!doctype html><html><head>
<meta charset="utf-8"><title>TechVerse Shop</title>
<style>
:root{{--bg:#0b0e14;--card:#121826;--fg:#e5e9f0;--acc:#3b82f6;--muted:#8b93a7}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--fg);min-height:100vh}}
header{{background:#121826;border-bottom:1px solid #232a3b;padding:12px 24px;display:flex;align-items:center;gap:24px}}
header .logo{{font-weight:700;font-size:18px;color:var(--acc);letter-spacing:.5px}}
header nav a{{color:var(--muted);text-decoration:none;margin-right:16px;font-size:14px}}
header nav a:hover{{color:var(--fg)}}
main{{max-width:960px;margin:24px auto;padding:0 24px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid #232a3b;border-radius:10px;padding:16px}}
.card h3{{font-size:15px;margin-bottom:6px}}
.card .price{{color:#22c55e;font-weight:700}}
.card .desc{{color:var(--muted);font-size:13px}}
form{{background:var(--card);padding:20px;border-radius:10px;border:1px solid #232a3b;max-width:420px;margin:16px 0}}
input,textarea{{width:100%;background:#0b0e14;border:1px solid #232a3b;color:var(--fg);padding:8px 10px;border-radius:6px;margin:6px 0;font-size:14px}}
button{{background:var(--acc);border:0;color:#fff;padding:8px 18px;border-radius:6px;cursor:pointer}}
pre{{background:#0b0e14;border:1px solid #232a3b;padding:14px;border-radius:8px;overflow:auto}}
footer{{text-align:center;color:var(--muted);font-size:12px;padding:24px}}
h1,h2{{margin:12px 0}}
a{{color:var(--acc)}}
.msg{{background:#1a1f2e;padding:10px;border-radius:6px;border-left:3px solid var(--acc)}}
</style></head><body>
<header><div class="logo">TECHVERSE</div>
<nav>{}<a href="#"></a></nav></header>
<main>{}</main>
<footer>TechVerse Shop — todos os direitos reservados {}</footer>
</body></html>"""

NAV = '<a href="/">Início</a><a href="/search">Busca</a><a href="/login">Entrar</a><a href="/feedback">Feedback</a>'


def page(title: str, body: str, nav: str = NAV) -> str:
    return BASE.format(nav, f"<h1>{title}</h1>{body}", "2026")


def q(sql: str, params: tuple = ()):
    return sqlite3.connect(DB).execute(sql, params).fetchall()


@app.route("/")
def index():
    products = q("SELECT * FROM products")
    cards = "".join(
        f'<div class="card"><h3>{p[1]}</h3><div class="price">R$ {p[2]:.2f}</div>'
        f'<div class="desc">{p[3]}</div><a href="/product/{p[0]}">ver</a></div>'
        for p in products
    )
    return page("Destaques", f'<div class="grid">{cards}</div>')


@app.route("/product/<int:pid>")
def product(pid):
    rows = q("SELECT * FROM products WHERE id=?", (pid,))
    if not rows:
        abort(404)
    p = rows[0]
    return page(p[1], f'<div class="card"><h3>{p[1]}</h3><div class="price">R$ {p[2]:.2f}</div><div class="desc">{p[3]}</div></div>')


# ---------------------------------------------------------------- SQLi (busca)
@app.route("/search")
def search():
    term = request.args.get("q", "")
    items = ""
    if term:
        # VULNERÁVEL: concatenação direta
        sql = f"SELECT name, price FROM products WHERE name LIKE '%{term}%'"
        try:
            for name, price in q(sql):
                items += f"<li>{name} — R$ {price:.2f}</li>"
        except Exception as exc:
            return page("Busca", f"<pre>Erro SQL: {exc}\n\nQuery: {sql}</pre>")
    return page("Busca", f'<form method="get"><input name="q" placeholder="Digite o produto…"><button>Buscar</button></form><ul>{items}</ul>')


# -------------------------------------------------- SQLi auth bypass (login)
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return page("Entrar", '<form method="post"><input name="u" placeholder="usuário"><input name="p" type="password" placeholder="senha"><button>Entrar</button></form>')
    u = request.form.get("u", "")
    p = request.form.get("p", "")
    sql = f"SELECT id, username, role FROM users WHERE username='{u}' AND password='{p}'"
    try:
        rows = q(sql)
    except Exception as exc:
        return page("Entrar", f"<pre>{exc}\n\n{sql}</pre>")
    if rows:
        session["uid"] = rows[0][0]
        session["role"] = rows[0][2]
        return redirect("/account")
    return page("Entrar", '<div class="msg">Credenciais inválidas</div><form method="post"><input name="u"><input name="p" type="password"><button>Entrar</button></form>')


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# --------------------------------------------------------------------- IDOR
@app.route("/orders/<int:oid>")
def orders(oid):
    if "uid" not in session:
        return redirect("/login")
    # VULNERÁVEL: não valida se o pedido pertence ao usuário logado
    rows = q("SELECT id, item, total FROM orders WHERE id=?", (oid,))
    if not rows:
        abort(404)
    o = rows[0]
    return page(f"Pedido #{o[0]}", f'<div class="card"><h3>{o[1]}</h3><div class="price">R$ {o[2]:.2f}</div></div>')


@app.route("/account")
def account():
    if "uid" not in session:
        return redirect("/login")
    rows = q("SELECT username, role FROM users WHERE id=?", (session["uid"],))
    u = rows[0]
    meus = "".join(f'<li><a href="/orders/{o[0]}">Pedido #{o[0]}</a></li>' for o in q("SELECT id FROM orders WHERE user_id=?", (session["uid"],)))
    return page("Minha conta", f'<div class="card"><h3>{u[0]}</h3><div class="desc">papel: {u[1]}</div></div><h2>Meus pedidos</h2><ul>{meus}</ul>')


# -------------------------------------------------------------- XSS stored
@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "POST":
        user = session.get("uid") and (lambda x: x[0][0])(q("SELECT username FROM users WHERE id=?", (session["uid"],))[:1]) or "anon"
        msg = request.form.get("msg", "")
        # VULNERÁVEL: ecoa sem escapar (XSS armazenado)
        sql = f"INSERT INTO feedback(user, msg) VALUES('{user}', '{msg}')"
        q(sql)
    msgs = "".join(f'<div class="msg">{f[1]}: {f[2]}</div>' for f in q("SELECT * FROM feedback"))
    return page("Feedback", f'<form method="post"><textarea name="msg" placeholder="Deixe seu comentário…"></textarea><button>Enviar</button></form>{msgs}')


# --------------------------------------------------------------------- SSRF
@app.route("/api/status")
def status():
    target = request.args.get("url", "")
    if not target:
        return "use ?url=http://..."
    if not target.startswith("http"):
        return "somente http(s)"
    # VULNERÁVEL: permite URL interna/loopback/link-local
    try:
        with urllib.request.urlopen(target, timeout=5) as r:
            body = r.read(2000).decode("utf-8", "replace")
            return f"OK {r.status}\n<pre>{body}</pre>"
    except Exception as exc:
        return f"erro: {exc}"


# ------------------------------------------- command injection com blacklist
@app.route("/tools/ping")
def ping():
    host = request.args.get("host", "")
    # VULNERÁVEL: blacklist incompleta (não bloqueia | e $())
    if re.search(r"[;&`]", host):
        return "caracteres bloqueados"
    out = subprocess.getoutput(f"ping -c 2 {host}")
    return page("Ping", f"<pre>{out}</pre>")


# ---------------------------------------------------- broken access control
@app.route("/admin")
def admin():
    # VULNERÁVEL: confia apenas no papel gravado na sessão (session fixation)
    if session.get("role") != "admin":
        abort(403)
    return page("Painel admin", '<div class="card">Bem-vindo, admin. Dica: a chave do cofre está em um arquivo no servidor.</div>')


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)