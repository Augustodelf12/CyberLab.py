#!/usr/bin/env python3
"""
TechVerse Shop — loja web REALISTA e intencionalmente vulnerável (nível médio).

Roda apenas na rede isolada do CyberLab.

Vulnerabilidades plantadas (as rotas e mecânicas não mudam — só o visual):
  /search?q=              -> SQL injection (UNION-based)
  /login                  -> SQLi auth bypass + session fixation
  /orders/<id>            -> IDOR (acessar pedidos de outros)
  /feedback               -> XSS armazenado
  /api/status?url=        -> SSRF (requisição a URL interna)
  /tools/ping?host=       -> command injection com blacklist falha
  /admin                  -> broken access control (flag parcial)

Objetivo final: ler /flag.txt (via command injection).
"""
import os
import re
import sqlite3
import subprocess
import urllib.request

from flask import Flask, abort, redirect, request, session

app = Flask(__name__)
app.secret_key = "nao-e-tao-secreto-assim"

DB = "/tmp/shop.db"


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
        [
            ("admin", "T3chV3rse_Admin!99", "admin"),
            ("alice", "alice123", "user"),
            ("bob", "letmein", "user"),
        ],
    )
    db.executemany(
        "INSERT INTO products(name, price, desc) VALUES(?,?,?)",
        [
            ("Roteador Quantum", 299.90, "Wi-Fi 7, velocidades de 5.800 Mbps"),
            ("SSD 2TB NVMe", 899.00, "Leitura de 7000 MB/s, PCIe 4.0"),
            ("Teclado Mecânico RGB", 349.90, "Switches hot-swappable"),
            ("Monitor 4K 27\"", 1899.00, "144Hz, 1ms, painel IPS"),
            ("Webcam 4K", 499.90, "Foco automático por IA"),
        ],
    )
    db.executemany(
        "INSERT INTO orders(user_id, item, total) VALUES(?,?,?)",
        [
            (1, "SSD 2TB NVMe", 899.00),
            (2, "Webcam 4K", 499.90),
            (1, "Roteador Quantum", 299.90),
        ],
    )
    db.execute("INSERT INTO feedback(user, msg) VALUES('admin','Bem-vindo à TechVerse Shop!')")
    db.commit()
    db.close()


init_db()

# ------------------------------------------------------------------------- UI
BASE = """<!doctype html><html lang="pt-BR"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TechVerse Shop</title>
  <style>
    :root { --bg:#060b09; --bg-soft:#0a120f; --surface:#111d17; --text:#e6f2ee;
      --muted:#87a49b; --brand:#2dd4bf; --brand-2:#99f6e8; --border:#1b2b23;
      --radius:12px; --radius-sm:9px; }
    * { box-sizing:border-box; margin:0; padding:0; }
    body { font-family:'Inter', 'Segoe UI', sans-serif; background:var(--bg); color:var(--text); line-height:1.65; min-height:100vh; }
    a { color:var(--brand); text-decoration:none; }

    header { position:sticky; top:0; z-index:10; background:rgba(6,11,9,0.78); backdrop-filter:blur(12px); border-bottom:1px solid var(--border); padding:12px 26px; }
    .nav-inner { max-width:1100px; margin:0 auto; display:flex; align-items:center; gap:24px; }
    header .brand { font-weight:800; font-size:17px; color:var(--text); display:flex; gap:8px; align-items:center; }
    header .brand svg { width:20px; height:20px; color:var(--brand); }
    header nav { display:flex; gap:18px; flex:1; }
    header nav a { color:var(--muted); font-size:14px; transition:color .15s; }
    header nav a:hover { color:var(--text); }
    main { max-width:1100px; margin:28px auto; padding:0 24px; }

    h1 { font-size:28px; font-weight:800; letter-spacing:-0.01em; margin-bottom:22px;
      background:linear-gradient(115deg, var(--text) 20%, var(--brand), var(--brand-2));
      -webkit-background-clip:text; background-clip:text; color:transparent; }
    h2 { font-size:18px; margin:22px 0 12px; font-weight:700; color:var(--text); }
    p.lead { color:var(--muted); max-width:650px; margin-bottom:22px; }

    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:16px; }
    .card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:18px; transition:transform .18s, border-color .18s, box-shadow .18s; }
    .card:hover { transform:translateY(-3px); border-color:var(--brand); box-shadow:0 12px 30px rgba(0,0,0,.4); }
    .card h3 { font-size:15.5px; margin-bottom:6px; font-weight:600; }
    .card .price { color:var(--brand); font-weight:700; margin-bottom:6px; }
    .card .desc { color:var(--muted); font-size:13px; }
    .card a.view { font-size:13px; color:var(--brand); margin-top:10px; display:inline-block; }

    form { background:var(--surface); padding:22px; border-radius:var(--radius); border:1px solid var(--border); max-width:440px; margin:16px 0; }
    .field { margin-bottom:12px; }
    label { display:block; font-size:13px; color:var(--muted); margin-bottom:5px; }
    input, textarea { width:100%; background:#0a110f; border:1px solid var(--border); color:var(--text); padding:9px 11px; border-radius:8px; font-size:14px; }
    input:focus, textarea:focus { outline:none; border-color:var(--brand); box-shadow:0 0 0 1px var(--brand); }
    button { background:linear-gradient(135deg, var(--brand), var(--brand-2)); color:#0a1a16; border:0; padding:9px 20px; border-radius:8px; cursor:pointer; font-weight:600; }

    .msg { background:var(--brand-soft-strong, rgba(45,212,191,0.1)); padding:12px 16px; border-radius:var(--radius-sm); border:1px solid var(--border); border-left:3px solid var(--brand); margin:12px 0; color:var(--text-muted); font-size:14px; }
    pre { background:#0a0e0d; border:1px solid var(--border); border-radius:var(--radius-sm); padding:14px 16px; overflow:auto; color:#b9d2cb; font-family:'JetBrains Mono', monospace; font-size:13px; margin:10px 0; }
    footer { text-align:center; color:var(--muted); font-size:12.5px; padding:34px 24px; border-top:1px solid var(--border); margin-top:60px; }
  </style>
</head><body>
  <header><div class="nav-inner">
    <a class="brand" href="/">
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="2.5" y="4" width="19" height="15" rx="2.2" stroke="currentColor" stroke-width="1.6"/><path d="M6.5 9.5L9.5 12L6.5 14.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 15H15.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
      <span>TechVerse</span>
    </a>
    <nav>{nav}</nav>
  </div></header>
  <main>{body}</main>
  <footer>TechVerse Shop © 2026 — laboratório de pentest</footer>
</body></html>"""

NAV = '<a href="/">Início</a><a href="/search">Busca</a><a href="/feedback">Feedback</a>'


def page(title: str, body: str, nav: str | None = None) -> str:
    # usa replace() em vez de format() (o CSS tem {-} pelo meio)
    return BASE.replace("{nav}", nav or NAV).replace("{body}", f"<h1>{title}</h1>{body}")


def q(sql: str, params: tuple = ()) -> list:
    return sqlite3.connect(DB).execute(sql, params).fetchall()


def _product_card(p) -> str:
    return (
        '<div class="card">'
        f"<h3>{p[1]}</h3>"
        f'<div class="price">R$ {p[2]:,.2f}</div>'
        f'<div class="desc">{p[3]}</div>'
        f'<a class="view" href="/product/{p[0]}">Ver detalhe →</a>'
        "</div>"
    )


# ================================================================ PÁGINAS
@app.route("/")
def index():
    products = q("SELECT * FROM products")
    featured = "".join(_product_card(p) for p in products)
    return page("Destaques da semana", f'<p class="lead">Selecionamos o que há de melhor em hardware de ponta, com foco em performance e valor.</p><div class="grid">{featured}</div>')


@app.route("/product/<int:pid>")
def product(pid):
    rows = q("SELECT * FROM products WHERE id=?", (pid,))
    if not rows:
        abort(404)
    p = rows[0]
    return page(
        p[1],
        f'<div class="card"><h3>{p[1]}</h3><div class="price">R$ {p[2]:,.2f}</div><p class="desc">{p[3]}</p></div>',
    )


# ------------------------------------------------------------------ SQLi
@app.route("/search")
def search():
    term = request.args.get("q", "")
    items = ""
    if term:
        # VULNERÁVEL: concatenação direta na query SQL
        sql = f"SELECT name, price FROM products WHERE name LIKE '%{term}%'"
        try:
            for name, price in q(sql):
                items += f"<li>{name} — R$ {price:.2f}</li>"
        except Exception as exc:
            return page("Busca", f"<pre>Erro SQL: {exc}\n\nQuery: {sql}</pre>")
    return page(
        "Busca",
        f'<form method="get"><div class="field"><label>Produto:</label><input name="q" placeholder="Digite o produto…"></div><button>Buscar</button></form><ul style="padding-left:22px">{items}</ul>',
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return page(
            "Entrar",
            '<form method="post"><div class="field"><label>Usuário:</label><input name="u"></div><div class="field"><label>Senha:</label><input name="p" type="password"></div><button>Entrar</button></form>',
        )
    u = request.form.get("u", "")
    p = request.form.get("p", "")
    sql = f"SELECT id, username, role FROM users WHERE username='{u}' AND password='{p}'"
    try:
        rows = q(sql)
    except Exception as exc:
        return page("Entrar", f"<pre>Erro SQL: {exc}\n\nQuery: {sql}</pre>")
    if rows:
        session["uid"] = rows[0][0]        # fixation: sessão gravada (bypass)
        session["role"] = rows[0][2]
        return redirect("/account")
    return page(
        "Entrar",
        '<div class="msg">Credenciais inválidas.</div><form method="post"><div class="field"><label>Usuário:</label><input name="u"></div><div class="field"><label>Senha:</label><input name="p" type="password"></div><button>Entrar</button></form>',
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ------------------------------------------------------------------ IDOR
@app.route("/orders/<int:oid>")
def orders(oid):
    if "uid" not in session:
        return redirect("/login")
    # VULNERÁVEL: não valida se o pedido pertence ao usuário logado
    rows = q("SELECT id, item, total FROM orders WHERE id=?", (oid,))
    if not rows:
        abort(404)
    o = rows[0]
    return page(f"Pedido #{o[0]}", f'<div class="card"><h3>{o[1]}</h3><div class="price">R$ {o[2]:,.2f}</div></div>')


@app.route("/account")
def account():
    if "uid" not in session:
        return redirect("/login")
    rows = q("SELECT username, role FROM users WHERE id=?", (session["uid"],))
    u = rows[0]
    orders_rows = q("SELECT id, total FROM orders WHERE user_id=?", (session["uid"],))
    meus = "".join(
        f'<li><a href="/orders/{oid}">Pedido #{oid}</a> — R$ {total:.2f}</li>'
        for oid, total in orders_rows
    )
    return page(
        "Minha conta",
        f'<div class="card"><h3>{u[0]}</h3><div class="desc">papel: {u[1]}</div></div><h2>Meus pedidos</h2><ul style="padding-left:22px">{meus}</ul>',
    )


# -------------------------------------------------------------- XSS stored
@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "POST":
        user = "anon"
        if session.get("uid"):
            rows = q("SELECT username FROM users WHERE id=?", (session["uid"],))
            if rows:
                user = rows[0][0]
        msg = request.form.get("msg", "")
        # VULNERÁVEL: ecoa sem escapar (XSS armazenado)
        q(f"INSERT INTO feedback(user, msg) VALUES('{user}', '{msg}')")
    msgs = "".join(f'<div class="msg"><strong>{f[1]}</strong>: {f[2]}</div>' for f in q("SELECT * FROM feedback"))
    return page(
        "Feedback",
        f'<form method="post"><div class="field"><label>Mensagem:</label><textarea name="msg" rows="3"></textarea></div><button>Enviar</button></form>{msgs}',
    )


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


# ------------------------------------------------ command injection (blacklist falha)
@app.route("/tools/ping")
def ping():
    host = request.args.get("host", "")
    # VULNERÁVEL: blacklist incompleta (não bloqueia '|' nem '$()')
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
    return page("Painel admin", '<div class="msg">Atenção, admin: o segredo está em um arquivo no servidor.</div>')


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)