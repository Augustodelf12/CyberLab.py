#!/usr/bin/env python3
"""
WebVuln — aplicação web INTENCIONALMENTE vulnerável.

Roda apenas dentro da rede isolada do CyberLab. Nunca exponha fora do lab.

Vulnerabilidades plantadas:
  /login    -> SQL injection (auth bypass)
  /search   -> SQL injection (UNION-based, exfiltração)
  /ping     -> command injection
  /greet    -> XSS refletido
  /read     -> Local File Inclusion / path traversal
"""
import os
import sqlite3
import subprocess

from flask import Flask, request

app = Flask(__name__)
DB = "/tmp/webvuln.db"


def init_db() -> None:
    if os.path.exists(DB):
        return
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, password TEXT)")
    db.execute("CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, price REAL)")
    db.execute("CREATE TABLE secrets(id INTEGER PRIMARY KEY, flag TEXT)")
    db.executemany(
        "INSERT INTO users(username, password) VALUES(?, ?)",
        [("admin", "Sup3rS3cret!2024"), ("joao", "senha123"), ("maria", "qwerty")],
    )
    db.executemany(
        "INSERT INTO products(name, price) VALUES(?, ?)",
        [("notebook", 3500.0), ("mouse", 45.5), ("teclado", 120.0), ("monitor", 899.9)],
    )
    db.execute("INSERT INTO secrets(flag) VALUES('CYBERLAB{sql1_un10n_xtr4ct}')")
    db.commit()
    db.close()


init_db()

PAGE = """<!doctype html>
<html><head><title>WebVuln Shop</title>
<style>body{{font-family:monospace;background:#111;color:#0f0;margin:2em}}
a{{color:#0ff}} input{{background:#000;color:#0f0;border:1px solid #0f0}}</style>
</head><body>{body}</body></html>"""


def page(body: str) -> str:
    return PAGE.format(body=body)


@app.route("/")
def index():
    return page(
        """<h1>WebVuln Shop</h1>
        <p>Loja de exemplo "segura". Nada para ver aqui.</p>
        <ul>
          <li><a href="/login">/login</a> — área restrita</li>
          <li><a href="/search?q=mouse">/search?q=</a> — busca de produtos</li>
          <li><a href="/ping?host=127.0.0.1">/ping?host=</a> — diagnóstico de rede</li>
          <li><a href="/greet?name=visitante">/greet?name=</a> — saudação</li>
          <li><a href="/read?file=/etc/hostname">/read?file=</a> — leitor de arquivos</li>
        </ul>
        <p><!-- TODO: lembrar que a senha do admin está na tabela users,
        e tem uma flag escondida na tabela secrets... --></p>"""
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return page(
            """<h1>Login</h1>
            <form method="post">
              user: <input name="u"><br>
              pass: <input name="p" type="password"><br>
              <input type="submit" value="entrar">
            </form>"""
        )
    u = request.form.get("u", "")
    p = request.form.get("p", "")
    # VULNERÁVEL: concatenação direta na query
    query = f"SELECT username FROM users WHERE username='{u}' AND password='{p}'"
    try:
        rows = sqlite3.connect(DB).execute(query).fetchall()
    except Exception as exc:  # erro vaza a query -> ajuda no aprendizado de SQLi
        return page(f"<h1>Erro SQL</h1><pre>{exc}\n\nQuery: {query}</pre>")
    if rows:
        return page(f"<h1>Bem-vindo, {rows[0][0]}!</h1><p>Sessão iniciada.</p>")
    return page("<h1>Credenciais inválidas</h1>")


@app.route("/search")
def search():
    q = request.args.get("q", "")
    # VULNERÁVEL: UNION-based SQLi
    query = f"SELECT name, price FROM products WHERE name LIKE '%{q}%'"
    try:
        rows = sqlite3.connect(DB).execute(query).fetchall()
    except Exception as exc:
        return page(f"<h1>Erro SQL</h1><pre>{exc}\n\nQuery: {query}</pre>")
    items = "".join(f"<li>{name} — R$ {price}</li>" for name, price in rows)
    return page(f"<h1>Resultados para: {q}</h1><ul>{items}</ul>")


@app.route("/ping")
def ping():
    host = request.args.get("host", "")
    if not host:
        return page("<h1>Use /ping?host=IP</h1>")
    # VULNERÁVEL: command injection
    out = subprocess.getoutput(f"ping -c 2 {host}")
    return page(f"<h1>ping {host}</h1><pre>{out}</pre>")


@app.route("/greet")
def greet():
    name = request.args.get("name", "visitante")
    # VULNERÁVEL: XSS refletido (sem escaping)
    return page(f"<h1>Olá, {name}!</h1>")


@app.route("/read")
def read_file():
    path = request.args.get("file", "")
    if not path:
        return page("<h1>Use /read?file=/caminho</h1>")
    # VULNERÁVEL: LFI / path traversal
    try:
        with open(path, "r", errors="replace") as fh:
            content = fh.read(8192)
        return page(f"<h1>{path}</h1><pre>{content}</pre>")
    except Exception as exc:
        return page(f"<h1>Erro</h1><pre>{exc}</pre>")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
