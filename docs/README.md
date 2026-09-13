# CyberLab — Guias de Hacking (writeups)

Documentação completa de como consignar a explorar todos os alvos do laboratório.
Use estes guias para aprender; cada lab tem **flags** (objetivos) para você
reproduzir.

> Ambiente **isolado**. Tudo roda dentro da rede `172.30.0.0/24` (internal).
> Nunca exponha os alvos fora do lab.

## Índice

| Alvo | Tipo | Dificuldade | Guia |
|---|---|---|---|
| `webvuln` | Web app | Fácil | [webvuln.md](webvuln.md) |
| `sshweak` | SSH brute-force | Fácil | [sshweak.md](sshweak.md) |
| `ftpanon` | FTP anônimo | Fácil | [ftpanon.md](ftpanon.md) |
| `shopvuln` | Loja web realista | **Média** | [shopvuln.md](shopvuln.md) |
| `privesc` | Linux privesc | **Média** | [privesc.md](privesc.md) |

## Metodologia padrão

1. **Enumeração** — `nmap`, `gobuster`/`ffuf` (ou o `portscan.py` incluso),
   identificar versões e tecnologias.
2. **Identificar a falha** — testar inputs (SQLi, XSS, IDOR, SSRF, cmd injection).
3. **Explorar** — ganhar acesso inicial (shell/credenciais).
4. **Pós-exploração** — escalar privilégio, exfiltrar flags.
5. **Pivotar** — usar a máquina comprometida para atacar os vizinhos.

```bash
# comece mapeando a rede do lab (do atacante):
python3 /root/tools/portscan.py 172.30.0.0 1-254
```