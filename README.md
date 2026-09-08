# CyberLab

Laboratório **local e isolado** de pentest/rede para estudo: um exército de
máquinas-alvo e uma máquina atacante rodando como containers Docker leves,
geridos por uma TUI de terminal (Textual) e por uma CLI.

Feito para treinar red team e testar ferramentas próprias em Python **sem
peso no PC** e sem risco de escapar do lab. Multiplataforma: **Linux** e
**Windows** (e macOS).

---

## O que tem dentro

| Componente | Descrição |
|---|---|
| `cyberlab-attacker` | Atacante (debian-slim + nmap, hydra, scapy, paramiko, impacket…) com suas ferramentas em `/root/tools` |
| `cyberlab-webvuln-N` | Web app vulnerável (SQLi, XSS, LFI, command injection) |
| `cyberlab-sshweak-N` | SSH com senhas fracas (brute-force) |
| `cyberlab-ftpanon-N` | FTP anônimo com arquivos sensíveis |
| `cyberlab-net` | Rede *internal* (`172.30.0.0/24`) — sem rota para a internet |

Cada alvo consome **poucos MB de RAM**; suba quantos quiser.

## Topologia

```
              cyberlab-net 172.30.0.0/24 (internal)
 ┌────────────────────────────────────────────────────┐
 │  attacker (.2)        webvuln-1 (.3)                │
 │                        sshweak-1 (.4)               │
 │                       ftpanon-1 (.5)                │
 └────────────────────────────────────────────────────┘
  [internet = desligado por padrão; toggle liga NAT só no attacker]
```

## Pré-requisitos

- **Docker**:
  - Linux: Docker Engine (+ seu usuário no grupo `docker`).
  - Windows: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
    (com backend WSL 2, recomendado). O daemon precisa estar rodando.
- **Python 3.10+** (no Windows, instale marcando "Add Python to PATH").

## Instalação

### Linux / macOS

```bash
cd cyberlab
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# uma vez (constrói as imagens; demora alguns minutos na primeira vez):
.venv/bin/python main.py --setup
```

### Windows (PowerShell)

```powershell
cd cyberlab
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# uma vez:
.venv\Scripts\python main.py --setup
```

> **Sobre o terminal embutido no Windows:** a TUI e o dashboard funcionam
> nativamente, mas as abas de terminal interativo usam PTY (POSIX) e não
> funcionam no Windows nativo. Para a experiência completa, rode a TUI dentro
> do **WSL 2** (o Docker também fica no WSL). Alternativamente, no Windows
> use a TUI para gerenciar e abra os terminais por fora:
> `docker exec -it cyberlab-attacker bash` (é monitorado pelo dashboard mesmo assim).

## Comando global (`cyberlab_py`)

Para usar de qualquer lugar do PC, como um comando comum (`nc`, `nmap`…):

```bash
# Linux/macOS
.venv/bin/python main.py --install

# Windows
.venv\Scripts\python main.py --install
```

Depois, de **qualquer diretório**:

```bash
cyberlab_py --status
cyberlab_py target add ./meu-alvo
cyberlab_py tool run scanner 172.30.0.3 1-1024
cyberlab_py              # abre a TUI
```

- Linux/macOS: instala em `~/.local/bin/cyberlab_py`.
- Windows: instala em `%APPDATA%\Python\Scripts\cyberlab_py.cmd` e tenta
  atualizar o PATH (abra um novo terminal).

Remova com `--uninstall`.

## Uso (CLI)

```bash
cyberlab_py                    # abre a TUI / dashboard
cyberlab_py --status           # estado rápido no stdout
cyberlab_py --setup            # rede + imagens faltantes
cyberlab_py --rebuild          # reconstrói todas as imagens
cyberlab_py --nuke             # remove containers e rede do lab
```

### Compilar alvos e ferramentas

Qualquer pasta pode virar uma máquina do lab (alvo) ou uma ferramenta:

```bash
# === ALVOS (pasta com Dockerfile vira VM-alvo) ===
cyberlab_py target add ./minha-app-vulneravel [--name meu-alvo]
cyberlab_py target list                 # built-in + custom
cyberlab_py target spawn meu-alvo
cyberlab_py target remove meu-alvo

# === FERRAMENTAS (sincronizadas para /root/tools do atacante) ===
cyberlab_py tool add ./meu-scanner [--name scanner]
cyberlab_py tool list
cyberlab_py tool run scanner 172.30.0.3 1-1024
cyberlab_py tool remove scanner
```

Entrypoint de ferramenta detectado automaticamente (ordem): `main.py` →
`app.py` → `run.py` → `tool.py` → `run.sh`/`main.sh` → executável `main`.

### Atalhos da TUI

| Tecla | Ação |
|---|---|
| `enter` (na linha da máquina) | abre o terminal dela numa aba |
| `ctrl+n` | cria novo alvo (menu de tipos) |
| `a` | importa pasta como alvo ou ferramenta |
| `s` | liga/desliga a máquina selecionada |
| `x` | destrói a máquina selecionada (pede confirmação) |
| `i` | alterna internet (NAT) na máquina atacante |
| `f2` | alterna o foco entre terminal e tabela |
| `ctrl+q` | sai |

As abas de terminal têm scrollback (roda do mouse, Shift+setas, Shift+PgUp/PgDn).

## Treinar / testar suas ferramentas

A pasta `tools/` é montada em `/root/tools` **dentro do atacante**:

1. Escreva seu script em `tools/` (ex.: `portscan.py` já incluso),
   ou registre via `cyberlab_py tool add <pasta>`.
2. Na aba do atacante:
   ```bash
   python3 portscan.py 172.30.0.3 1-1024
   ```

Instalar uma lib nova no atacante: ligue a internet (tecla `i`) e rode
`pip install`, **ou** adicione ao `docker/attacker.Dockerfile` e rode
`cyberlab_py --rebuild` (mais reprodutível).

## Objetivos (flags) de exemplo

| Alvo | Como | Flag |
|---|---|---|
| webvuln | `/search?q=' UNION SELECT flag,2 FROM secrets-- -` | `CYBERLAB{sql1_un10n_xtr4ct}` |
| webvuln | `/ping?host=127.0.0.1;cat /flag.txt` | `CYBERLAB{w3b_pwn3d_c0ngr4tz}` |
| webvuln | `/login` com `' OR '1'='1` | bypass de auth |
| sshweak | hydra contra usuários fracos (`root:toor`, `admin:admin`, `user:password`, `backup:backup123`) | `CYBERLAB{ssh_brut3_f0rc3_w1n}` em `/root/flag.txt` |
| ftpanon | login anônimo, baixar `pub/flag.txt` | `CYBERLAB{ftp_4n0nym0us_l00t}` |

## Segurança

- A rede é `internal: true`: os alvos **não têm internet** e nenhuma porta é
  publicada no host. Todo o tráfego fica em `cyberlab-net`.
- O `attacker` nasce sem internet; ganha NAT só se você ativar (tecla `i`).
- **Nunca** altere os Dockerfiles para publicar portas ou remover o `internal`
  — aí o lab deixa de ser isolado e passa a expor máquinas vulneráveis na LAN.

## Estrutura

```
cyberlab/
├── main.py                  # CLI (target/tool/install) + entrypoint da TUI
├── requirements.txt
├── .gitignore
├── registry.json            # alvos/ferramentas custom (criado no 1º uso)
├── lab/
│   ├── manager.py           # Docker SDK: rede, containers, métricas, registry
│   ├── terminal.py          # widget Terminal (PTY + pyte + scrollback)
│   └── app.py               # TUI (Textual)
├── docker/                  # Dockerfiles do atacante e dos alvos
├── tools/                   # suas ferramentas (montada no atacante)
└── tests/                   # testes de fumaça (manager, TUI, terminal, custom)
```

### Rodar os testes

```bash
.venv/bin/python tests/test_manager.py    # cria/destrói alvos de verdade
.venv/bin/python tests/test_tui.py        # TUI headless (modo run_test)
.venv/bin/python tests/test_terminal.py   # terminal embutido + scrollback
.venv/bin/python tests/test_custom.py     # alvos/ferramentas custom
```

## Problemas comuns

- **`docker indisponível`**: inicie o daemon (`sudo systemctl start docker` no
  Linux; abra o Docker Desktop no Windows) e garanta estar no grupo `docker`.
- **Dentro do VS Code (Flatpak)** no Linux: o terminal embutido do editor é um
  sandbox; rode a TUI no terminal do sistema para acessar o Docker do host.
- **Terminal embutido não abre (Windows)**: use WSL 2 (recomendado) ou abra os
  terminais por fora com `docker exec -it`.
- **Lentidão no primeiro uso**: é o build das imagens (`--setup`); depois os
  containers sobem em segundos.