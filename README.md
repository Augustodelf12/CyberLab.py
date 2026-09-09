# CyberLab

Laboratório **local e isolado** de pentest/rede para estudo: um exército de
máquinas-alvo e uma máquina atacante rodando como containers Docker leves,
geridos por uma TUI de terminal (Textual) e por uma CLI.

Feito para treinar red team e testar ferramentas próprias em Python **sem
peso no PC** e sem risco de escapar do lab. Multiplataforma: **Linux**,
**Windows** e **macOS**.

---

## O que tem dentro

| Componente | Descrição |
|---|---|
| `cyberlab-attacker` | Atacante (debian-slim + nmap, hydra, scapy, paramiko, impacket, vim, nano, neofetch, htop…) com suas ferramentas em `/root/tools` |
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
    (recomendado backend WSL 2). O daemon precisa estar rodando.
- **Python 3.10+**.

## Instalação

A ferramenta é um pacote Python: instale **de qualquer lugar** — não precisa
clonar nem ter as pastas do projeto. Os Dockerfiles e o exemplo de ferramenta
já vão embutidos no pacote.

### Linux / macOS

```bash
pipx install git+https://github.com/Augustodelf12/CyberLab.py

# sem pipx:
python3 -m venv ~/.cyberlab-venv
~/.cyberlab-venv/bin/pip install git+https://github.com/Augustodelf12/CyberLab.py
~/.cyberlab-venv/bin/cyberlab_py --install   # cria o comando global
```

### Windows (PowerShell)

```powershell
pip install git+https://github.com/Augustodelf12/CyberLab.py
cyberlab_py --install     # se 'cyberlab_py' não estiver no PATH
```

### Primeiro uso

```bash
cyberlab_py --setup   # baixa/constrói as imagens (alguns minutos na 1ª vez)
```

### Modo desenvolvimento (clonar)

```bash
git clone https://github.com/Augustodelf12/CyberLab.py
cd CyberLab.py
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/cyberlab_py --setup
```

## Uso (CLI)

```bash
cyberlab_py            # abre a TUI / dashboard
cyberlab_py --status   # estado rápido no stdout
cyberlab_py --setup    # rede + imagens faltantes
cyberlab_py --rebuild  # reconstrói todas as imagens
cyberlab_py --nuke     # remove containers e rede do lab
cyberlab_py --install / --uninstall   # comando global no PATH
cyberlab_py --update                  # atualiza o app (sem desinstalar)
cyberlab_py --audit                   # audita o isolamento de rede do lab
```

### Compilar alvos e ferramentas

Qualquer pasta pode virar uma máquina do lab (alvo) ou uma ferramenta:

```bash
# === ALVOS (pasta com Dockerfile vira VM-alvo) ===
cyberlab_py target add ./minha-app-vulneravel [--name meu-alvo]
cyberlab_py target list                 # built-in + custom
cyberlab_py target spawn meu-alvo
cyberlab_py target remove meu-alvo

# === FERRAMENTAS (sincronizadas para dentro do atacante) ===
cyberlab_py tool add ./meu-scanner [--name scanner]
cyberlab_py tool list
cyberlab_py tool run scanner 172.30.0.3 1-1024
cyberlab_py tool remove scanner
```

Entrypoint de ferramenta detectado automaticamente (ordem): `main.py` →
`app.py` → `run.py` → `tool.py` → `run.sh`/`main.sh` → executável `main`.
Suas ferramentas/alvos custom ficam em `~/.local/share/cyberlab/` (Linux) ou
`%LOCALAPPDATA%\CyberLab\` (Windows).

### Atalhos da TUI

| Tecla | Ação |
|---|---|
| `enter` (na linha da máquina) | abre o terminal dela numa aba |
| `ctrl+n` | cria novo alvo (menu de tipos) |
| `a` | importa pasta como alvo ou ferramenta |
| `s` | liga/desliga a máquina selecionada |
| `x` | destrói a máquina selecionada (pede confirmação) |
| `i` | alterna internet (NAT) na máquina atacante |
| `u` | atualiza o app para a versão mais recente |
| `ctrl+p` | abre o command palette (importar, atualizar, tema, sair…) |
| `f2` | alterna o foco entre terminal e tabela |
| `ctrl+q` | sai |

As abas de terminal têm scrollback (roda do mouse, Shift+setas, Shift+PgUp/PgDn),
cores **16/256/24-bit (truecolor)**, alternate screen (nano/vim/less) e suporte
a modo de cursor. Para copiar a saída: **arraste com o mouse** para selecionar e
pressione **`Ctrl+Shift+C`** (sem seleção, copia a linha do cursor). Cole com
**`Ctrl+Shift+V`**.

> **Terminal embutido no Windows:** a TUI e o dashboard funcionam nativos,
> mas as abas de terminal usam PTY (POSIX) e não abrem no Windows nativo.
> Para a experiência completa rode a TUI dentro do **WSL 2** (onde o Docker
> também fica). Alternativa: gerencie pela TUI e abra terminais por fora
> (`docker exec -it cyberlab-attacker bash`) — o dashboard segue monitorando.

## Treinar / testar suas ferramentas

Suas ferramentas ficam dentro do atacante, em `/root/tools`:

1. Crie sua ferramenta em qualquer pasta e registre-a:
   ```bash
   cyberlab_py tool add ./meu-scanner --name scanner
   ```
2. Rode-a direto contra os alvos:
   ```bash
   cyberlab_py tool run scanner 172.30.0.3 1-1024
   ```
   ou, na aba do atacante:
   ```bash
   cd /root/tools/scanner && python3 main.py 172.30.0.3 1-1024
   ```
3. Um exemplo `portscan.py` já vem junto (em `/root/tools/portscan.py`).

Instalar libs novas no atacante: ligue a internet (tecla `i`) e rode
`pip install`, **ou** edite `lab/docker/attacker.Dockerfile` e rode
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
  — aí o lab deixa de ser isolado e expõe máquinas vulneráveis na LAN.

### Modo airgap (uso crítico)

Para garantir **zero conexão de rede externa** — ideal para pentest de código
crítico/sensível — rode com `CYBERLAB_AIRGAP=1`:

```bash
CYBERLAB_AIRGAP=1 cyberlab_py --setup
CYBERLAB_AIRGAP=1 cyberlab_py            # TUI com internet travada
```

Nesse modo o toggle de internet é desabilitado (o botão fica "travada"),
`--update` é bloqueado. Audite a qualquer momento:

```bash
cyberlab_py --audit
```

que verifica: rede interna, ausência de portas publicadas no host, atacante
sem NAT e containers restritos à rede do lab.

## Estrutura

```
CyberLab.py/
├── pyproject.toml            # empacotamento (entry point cyberlab_py)
├── main.py                   # shim p/ rodar da fonte (dev)
├── requirements.txt
├── .gitignore
├── lab/
│   ├── cli.py                # CLI (target/tool/setup/install…)
│   ├── manager.py            # Docker SDK: rede, containers, métricas, registry
│   ├── terminal.py           # widget Terminal (PTY + pyte + scrollback)
│   ├── paths.py              # assets embutidos + data dir do usuário
│   ├── app.py                # TUI (Textual)
│   ├── docker/               # Dockerfiles do atacante e dos alvos (package data)
│   └── examples/             # ferramentas de exemplo
└── tests/                    # testes de fumaça (manager, TUI, terminal, custom)
```

### Rodar os testes (desenvolvimento)

```bash
.venv/bin/python tests/test_manager.py    # cria/destrói alvos de verdade
.venv/bin/python tests/test_tui.py        # TUI headless (modo run_test)
.venv/bin/python tests/test_terminal.py   # terminal embutido + scrollback
.venv/bin/python tests/test_custom.py     # alvos/ferramentas custom
```

## Problemas comuns

- **`docker indisponível`**: inicie o daemon (`sudo systemctl start docker` no
  Linux; abra o Docker Desktop no Windows) e garanta estar no grupo `docker`.
- **`cyberlab_py` não é reconhecido**: instale com `pipx` (Linux) ou rode
  `cyberlab_py --install` para criar o launcher global; feche e reabra o terminal.
- **VS Code (Flatpak)** no Linux: o terminal embutido do editor é um sandbox;
  rode a TUI no terminal do sistema para acessar o Docker do host.
- **Terminal embutido não abre (Windows)**: use WSL 2 ou `docker exec -it` por fora.
- **Lentidão no primeiro uso**: é o build das imagens (`--setup`); depois os
  containers sobem em segundos.