"""
CyberLab — CLI. Instalável como comando global via pipx/pip:

    pipx install git+https://github.com/<user>/CyberLab.py
    cyberlab_py --setup

Sem argumentos, abre a TUI (dashboard).
"""
from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

from .manager import AIRGAP, LabManager, TARGETS

# Fonte de atualização (override com a env CYBERLAB_UPDATE_URL)
UPDATE_URL = os.environ.get(
    "CYBERLAB_UPDATE_URL",
    "git+https://github.com/Augustodelf12/CyberLab.py",
)


def _manager() -> LabManager:
    m = LabManager()
    if not m.ping():
        print("ERRO: não consegui falar com o daemon do Docker.", file=sys.stderr)
        print("  Linux:  sudo systemctl start docker", file=sys.stderr)
        print("  Windows: abra o Docker Desktop", file=sys.stderr)
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
    m.enforce_airgap()
    print("✔ lab pronto — rode  cyberlab_py  para abrir a TUI")
    return 0


def cli_status() -> int:
    m = _manager()
    machines = m.machines()
    stats = m.sample_stats()
    if not machines:
        print("lab vazio — rode  cyberlab_py --setup")
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
def _is_windows() -> bool:
    return sys.platform == "win32"


def _in_venv() -> bool:
    """True se este Python é um ambiente virtual (venv/pipx)."""
    return sys.prefix != sys.base_prefix


def _bin_dir() -> Path:
    # Linux/macOS: ~/.local/bin · Windows: Scripts do ambiente Python EM USO
    if _is_windows():
        if _in_venv():
            # venv/pipx: Scripts do próprio ambiente — é este Python que o
            # lançador chama, então o lançador deve viver junto dele
            # (e não na base de usuário de um Python diferente).
            return Path(sys.prefix) / "Scripts"
        # Python "de sistema": base de usuário reportada pelo PRÓPRIO
        # interpretador (site.getuserbase) — %APPDATA%\Python no instalador
        # padrão, mas o caminho correto em variantes (ex.: Python da Microsoft
        # Store, PYTHONUSERBASE customizado). Nada de deduzir por env vars.
        import site

        return Path(site.getuserbase()) / "Scripts"
    return Path.home() / ".local" / "bin"


def _launcher_name() -> str:
    return "cyberlab_py.cmd" if _is_windows() else "cyberlab_py"


def _path_contains(bin_dir: Path) -> bool:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if _is_windows():
        want = str(bin_dir).lower()
        return any(p.lower() == want for p in parts)
    return str(bin_dir) in parts


def _windows_add_user_path(bin_dir: Path) -> bool:
    """Adiciona bin_dir ao Path do USUÁRIO via registro.

    O ``setx`` trunca valores em 1024 caracteres (corrompendo o PATH) e
    funde as entradas do sistema no usuário; o registro edita só a variável
    correta e sem limite de tamanho.
    """
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        ) as key:
            try:
                current, vtype = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current, vtype = "", winreg.REG_EXPAND_SZ
            parts = [p for p in str(current).split(os.pathsep) if p]
            want = str(bin_dir)
            if any(p.rstrip("\\").lower() == want.lower() for p in parts):
                return True
            winreg.SetValueEx(
                key, "Path", 0, vtype or winreg.REG_EXPAND_SZ,
                os.pathsep.join([*parts, want]),
            )
    except OSError:
        return False
    # avisa o sistema (Explorer/terminais novos relêem a variável)
    try:
        import ctypes

        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF,  # HWND_BROADCAST
            0x1A,    # WM_SETTINGCHANGE
            0, ctypes.c_wchar_p("Environment"),
            0x2,     # SMTO_ABORTIFHUNG
            5000, ctypes.byref(result),
        )
    except Exception:
        pass
    return True


def cli_install() -> int:
    """Gera um launcher global que chama este Python (-m lab.cli)."""
    bin_dir = _bin_dir()
    launcher = bin_dir / _launcher_name()
    py = sys.executable
    if _is_windows():
        content = f'@echo off\r\n"{py}" -m lab.cli %*\r\n'
    else:
        # aspas simples: um '$' no caminho do interpretador não é expandido
        content = f"#!/bin/sh\nexec '{py}' -m lab.cli \"$@\"\n"
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
        # newline="": o \r\n do .cmd não pode virar \r\r\n pela tradução
        # de newline do modo texto no Windows
        launcher.write_text(content, newline="")
        if not _is_windows():
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # não anunciar sucesso sem confirmar que o lançador existe de fato
        if not launcher.is_file():
            raise OSError(f"lançador {launcher} não apareceu após a escrita")
    except OSError as exc:
        print(f"ERRO: não consegui criar o lançador em {launcher}: {exc}",
              file=sys.stderr)
        return 1

    print(f"✔ comando 'cyberlab_py' instalado em {launcher}")
    if _path_contains(bin_dir):
        print("  já está no PATH — teste com: cyberlab_py --status")
    elif _is_windows():
        if _in_venv():
            # o lançador vive nos Scripts do venv: funciona com o venv ativado.
            # Não adicionamos venvs ao PATH do usuário (podem ser removidas).
            print(
                "  ambiente virtual detectado: o comando funciona com o venv "
                f"ativado ({bin_dir}). Para um comando global, instale com o "
                "Python do sistema ou use pipx."
            )
        elif _windows_add_user_path(bin_dir):
            print("  adicionado ao PATH do usuário — abra um NOVO terminal para valer")
        else:
            print(f"  sem permissão para editar o PATH — adicione manualmente: {bin_dir}")
    else:
        print('  adicione ao ~/.bashrc: export PATH="$HOME/.local/bin:$PATH"')
    return 0


def cli_uninstall() -> int:
    launcher = _bin_dir() / _launcher_name()
    if launcher.exists():
        try:
            launcher.unlink()
        except OSError as exc:
            print(f"ERRO: não consegui remover {launcher}: {exc}", file=sys.stderr)
            return 1
        print(f"✔ comando '{_launcher_name()}' removido de {launcher.parent}")
    else:
        print("comando 'cyberlab_py' não estava instalado")
    return 0


# ---------------------------------------------------------------- self-update
def self_update(log=lambda line: print(line)) -> int:
    """Reinstala o pacote direto do repositório (requer internet)."""
    log
    if AIRGAP:
        log("[airgap] atualização bloqueada (CYBERLAB_AIRGAP=1 — sem rede externa)")
        return 1
    log(f"atualizando de {UPDATE_URL} …")
    proc = subprocess.Popen(
        [sys.executable, "-m", "pip", "install", "--force-reinstall",
         "--no-deps", UPDATE_URL],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    if proc.stdout is None:
        return proc.wait()
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(line)
    code = proc.wait()
    if code == 0:
        log("✔ atualização concluída — reinicie o app (e rode `cyberlab_py --rebuild` se necessário)")
    else:
        log(f"[erro] atualização falhou (código {code})")
    return code


def cli_update() -> int:
    return self_update()


def cli_audit() -> int:
    m = _manager()
    m.enforce_airgap()  # airgap precisa ser um fato de rede, não um rótulo
    report = m.audit_isolation()
    checks = [
        ("rede_internal", "rede do lab é internal (sem rota para fora)"),
        ("sem_portas_publicadas", "nenhuma porta publicada no host"),
        ("atacante_sem_nat", "atacante sem NAT/ligação à internet"),
        ("containers_so_internal", "containers apenas na rede interna"),
    ]
    ok = True
    for key, desc in checks:
        good = bool(report.get(key, False))
        ok = ok and good
        print(f"[{'OK ' if good else 'RUIM'}] {desc}")
    print(f"\nmodo airgap: {'ATIVO' if AIRGAP else 'off (CYBERLAB_AIRGAP=1 para travar)'}")
    if ok:
        print("✔ ISOLADO — sem conexão de rede externa")
    else:
        print("✖ ATENÇÃO: há possíveis vias de saída de rede (veja acima)")
    return 0 if ok else 1


# ------------------------------------------------------------------- targets
def cmd_target(args) -> int:
    m = _manager()
    action = args.taction
    if action == "add":
        try:
            name = m.add_target(args.path, args.name)
            print(f"✔ alvo '{name}' compilado e registrado")
            print(f"  spawn:  cyberlab_py target spawn {name}")
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
            print(f"  rodar: cyberlab_py tool run {name}")
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
        try:
            m.remove_tool(args.name)
        except Exception as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            return 1
        print(f"✔ ferramenta '{args.name}' removida")
    else:
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cyberlab_py", description=__doc__.splitlines()[0])
    parser.add_argument("--setup", action="store_true", help="rede + imagens faltantes")
    parser.add_argument("--rebuild", action="store_true", help="reconstrói todas as imagens")
    parser.add_argument("--status", action="store_true", help="estado no stdout")
    parser.add_argument("--nuke", action="store_true", help="remove containers e rede")
    parser.add_argument("--install", action="store_true", help="instala o comando 'cyberlab_py' no PATH")
    parser.add_argument("--uninstall", action="store_true", help="remove o comando 'cyberlab_py' do PATH")
    parser.add_argument("--update", action="store_true", help="atualiza o app para a versão mais recente")
    parser.add_argument("--audit", action="store_true", help="audita o isolamento de rede do lab")

    sub = parser.add_subparsers(dest="command")

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
    if args.update:
        return cli_update()
    if args.audit:
        return cli_audit()

    from .app import CyberLabApp

    CyberLabApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())