#!/usr/bin/env python3
"""
CyberLab — laboratório local de pentest.

Sem argumentos, abre a TUI (dashboard):

    python main.py

Ações rápidas do ambiente:

    python main.py --setup     cria a rede e constrói as imagens que faltam
    python main.py --rebuild   reconstrói TODAS as imagens do zero
    python main.py --status    estado atual no stdout
    python main.py --nuke      remove todos os containers e a rede
    python main.py --install   instala o comando global 'cyberlab_py'
    python main.py --uninstall remove o comando global 'cyberlab_py'

Gerenciar alvos (pastas com Dockerfile viram VMs-alvo):

    python main.py target add <pasta> [--name N]   # builda e registra
    python main.py target list
    python main.py target spawn <nome>
    python main.py target remove <nome>

Gerenciar ferramentas (pastas sincronizadas para /root/tools do atacante;
entrypoint detectado: main.py | app.py | run.py | tool.py | run.sh | main.sh | main):

    python main.py tool add <pasta> [--name N]
    python main.py tool list
    python main.py tool run <nome> [args...]
    python main.py tool remove <nome>
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path


def _manager():
    from lab.manager import LabManager

    m = LabManager()
    if not m.ping():
        print("ERRO: não consegui falar com o daemon do Docker.", file=sys.stderr)
        print("  Verifique se o serviço está ativo:  sudo systemctl start docker", file=sys.stderr)
        raise SystemExit(1)
    return m


def cli_setup(rebuild: bool = False) -> int:
    m = _manager()
    print("• garantindo rede isolada…")
    m.ensure_network()
    missing = m.missing_images()
    if rebuild or missing:
        m.build_images(only=None if rebuild else missing, progress=print)
    else:
        print("• todas as imagens já existem (--rebuild força)")
    print("• garantindo máquina atacante…")
    m.ensure_attacker()
    print("✔ lab pronto — rode  python main.py  para abrir a TUI")
    return 0


def cli_status() -> int:
    m = _manager()
    machines = m.machines()
    stats = m.sample_stats()
    if not machines:
        print("lab vazio — rode  python main.py --setup")
        return 0
    print(f"{'máquina':<26}{'tipo':<12}{'estado':<10}{'ip':<14}{'cpu%':>7}{'ram':>9}")
    for mach in machines:
        cpu, mem, _ = stats.get(mach.name, (0.0, 0.0, 0.0))
        print(f"{mach.name:<26}{mach.kind:<12}{mach.status:<10}{mach.ip:<14}{cpu:>6.1f}%{mem:>7.0f}M")
    host = m.host_stats()
    print(
        f"\nhost: cpu {host['cpu']:.0f}% · "
        f"ram {host['mem_used_gb']:.1f}/{host['mem_total_gb']:.1f} GB"
    )
    print(f"internet do atacante: {'ON' if m.internet_enabled() else 'off'}")
    return 0


def cli_nuke() -> int:
    m = _manager()
    m.nuke(progress=print)
    print("✔ lab desmontado (imagens mantidas)")
    return 0


# --------------------------------------------------------- install no PATH
def _repo_dir() -> Path:
    from lab.manager import BASE_DIR

    return Path(BASE_DIR)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _venv_python(repo: Path) -> Path:
    if _is_windows():
        return repo / ".venv" / "Scripts" / "python.exe"
    return repo / ".venv" / "bin" / "python"


def _bin_dir() -> Path:
    # Linux/macOS: ~/.local/bin · Windows: %APPDATA%\Python\Scripts (padrão pip)
    if _is_windows():
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Python" / "Scripts"
    return Path.home() / ".local" / "bin"


def _launcher_name() -> str:
    return "cyberlab_py.cmd" if _is_windows() else "cyberlab_py"


def _launcher_code(repo: Path) -> str:
    """Launcher com caminho absoluto do venv + main.py (funciona de qualquer lugar)."""
    py = _venv_python(repo)
    main = repo / "main.py"
    if _is_windows():
        return f'@echo off\r\n"{py}" "{main}" %*\r\n'
    return f'#!/bin/sh\nexec "{py}" "{main}" "$@"\n'


def _path_contains(bin_dir: Path) -> bool:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if _is_windows():
        want = str(bin_dir).lower()
        return any(p.lower() == want for p in parts)
    return str(bin_dir) in parts


def cli_install() -> int:
    repo = _repo_dir()
    py = _venv_python(repo)
    if not py.is_file():
        print(f"ERRO: ambiente .venv não encontrado em {py.parent}", file=sys.stderr)
        print("  crie com:  python -m venv .venv && pip install -r requirements.txt", file=sys.stderr)
        return 1

    bin_dir = _bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / _launcher_name()
    launcher.write_text(_launcher_code(repo))
    if not _is_windows():
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    cmd = "cyberlab_py"
    print(f"✔ comando '{cmd}' instalado em {launcher}")
    if _path_contains(bin_dir):
        print(f"  já está no PATH — teste com: {cmd} status")
    elif _is_windows():
        try:
            import subprocess

            subprocess.run(
                ["setx", "PATH", os.environ.get("PATH", "") + os.pathsep + str(bin_dir)],
                check=False, capture_output=True,
            )
            print("  adicionado ao PATH do usuário — abra um NOVO terminal para valer")
        except Exception:
            print(f"  se não funcionar, adicione ao PATH manualmente: {bin_dir}")
    else:
        print('  adicione ao ~/.bashrc: export PATH="$HOME/.local/bin:$PATH"')
    return 0


def cli_uninstall() -> int:
    launcher = _bin_dir() / _launcher_name()
    if launcher.exists():
        launcher.unlink()
        print(f"✔ comando '{_launcher_name()}' removido de {launcher.parent}")
    else:
        print("comando 'cyberlab_py' não estava instalado")
    return 0


# ------------------------------------------------------------------- targets
def cmd_target(args) -> int:
    from lab.manager import TARGETS

    m = _manager()
    action = args.taction
    if action == "add":
        try:
            name = m.add_target(args.path, args.name)
            spec = m.all_targets()[name]
            print(f"✔ alvo '{name}' compilado e registrado")
            print(f"  imagem: {spec['image']}")
            print(f"  spawn:  python main.py target spawn {name}")
        except Exception as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            return 1
    elif action == "list":
        for name, spec in m.all_targets().items():
            origin = "built-in" if name in TARGETS else "custom"
            print(f"{name:<18} {origin:<9} {spec['image']:<32} {spec['desc']}")
        return 0
    elif action == "spawn":
        try:
            created = m.spawn_target(args.name)
            print(f"✔ alvo criado: {created}")
        except Exception as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            return 1
    elif action == "remove":
        m.remove_target(args.name)
        print(f"✔ alvo '{args.name}' removido do registry (e sua imagem)")
    else:
        return 2
    return 0


# ---------------------------------------------------------------------- tools
def cmd_tool(args) -> int:
    m = _manager()
    action = args.taction
    if action == "add":
        try:
            name = m.add_tool(args.path, args.name)
            print(f"✔ ferramenta '{name}' sincronizada para /root/tools/{name}")
            print(f"  rodar: python main.py tool run {name}")
        except Exception as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            return 1
    elif action == "list":
        tools = m.list_tools()
        if not tools:
            print("nenhuma ferramenta registrada")
        for name in tools:
            print(f"{name:<18} entry: {m.tool_entrypoint(name)}")
        return 0
    elif action == "run":
        if args.name not in m.list_tools():
            print(f"ERRO: ferramenta '{args.name}' não registrada (use 'tool add').",
                  file=sys.stderr)
            return 1
        try:
            code = m.run_tool(args.name, args.args)
        except Exception as exc:
            print(f"ERRO ao rodar: {exc}", file=sys.stderr)
            return 1
        return code or 0
    elif action == "remove":
        m.remove_tool(args.name)
        print(f"✔ ferramenta '{args.name}' removida")
    else:
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cyberlab", description=__doc__.splitlines()[0])
    parser.add_argument("--setup", action="store_true", help="rede + imagens faltantes")
    parser.add_argument("--rebuild", action="store_true", help="reconstrói todas as imagens")
    parser.add_argument("--status", action="store_true", help="estado no stdout")
    parser.add_argument("--nuke", action="store_true", help="remove containers e rede")
    parser.add_argument("--install", action="store_true", help="instala o comando 'cyberlab_py' no PATH")
    parser.add_argument("--uninstall", action="store_true", help="remove o comando 'cyberlab_py' do PATH")

    sub = parser.add_subparsers(dest="command")

    # target -------------------------------------------------------------
    target = sub.add_parser("target", help="gerenciar alvos")
    tsub = target.add_subparsers(dest="taction", required=True)
    tadd = tsub.add_parser("add", help="builda pasta com Dockerfile como alvo")
    tadd.add_argument("path", help="pasta com Dockerfile")
    tadd.add_argument("--name", help="nome do alvo (padrão: nome da pasta)")
    tsub.add_parser("list", help="lista alvos disponíveis")
    tspawn = tsub.add_parser("spawn", help="cria um container do alvo")
    tspawn.add_argument("name", help="nome do alvo")
    trm = tsub.add_parser("remove", help="remove alvo custom e sua imagem")
    trm.add_argument("name", help="nome do alvo")

    # tool ---------------------------------------------------------------
    tool = sub.add_parser("tool", help="gerenciar ferramentas")
    tosub = tool.add_subparsers(dest="taction", required=True)
    toadd = tosub.add_parser("add", help="sincroniza pasta para o atacante")
    toadd.add_argument("path", help="pasta da ferramenta")
    toadd.add_argument("--name", help="nome (padrão: nome da pasta)")
    tosub.add_parser("list", help="lista ferramentas")
    torun = tosub.add_parser("run", help="roda a ferramenta no atacante")
    torun.add_argument("name", help="nome da ferramenta")
    torun.add_argument("args", nargs=argparse.REMAINDER, help="argumentos da ferramenta")
    torm = tosub.add_parser("remove", help="remove ferramenta")
    torm.add_argument("name", help="nome da ferramenta")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "target":
        return cmd_target(args)
    if args.command == "tool":
        return cmd_tool(args)
    if args.setup or args.rebuild:
        return cli_setup(rebuild=args.rebuild)
    if args.status:
        return cli_status()
    if args.nuke:
        return cli_nuke()
    if args.install:
        return cli_install()
    if args.uninstall:
        return cli_uninstall()

    from lab.app import CyberLabApp

    CyberLabApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())