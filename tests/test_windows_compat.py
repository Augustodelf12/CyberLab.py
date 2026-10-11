#!/usr/bin/env python3
"""
Testes de compatibilidade com Windows (rodam em qualquer SO, sem Docker):

  - CLI/TUI não importam componentes POSIX (fcntl/ptyprocess/pyte)
  - Terminal degrada com mensagem informativa quando PTY não existe
  - _bin_dir()/instalador: venv x Python de sistema, verificação de criação,
    idempotência install/uninstall e PATH do Windows preservado (winreg fake)

    python tests/test_windows_compat.py
    pytest tests/test_windows_compat.py -q
"""
import asyncio
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lab.cli as cli  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CHECKS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    return subprocess.run(
        [sys.executable, "-m", "lab.cli", *args],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=90,
    )


@contextlib.contextmanager
def _fake_home(tmp: Path):
    old = os.environ.get("HOME")
    os.environ["HOME"] = str(tmp)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old


def _purge_module_tree(*names: str) -> None:
    """Remove os módulos E suas subentradas (pyte.screens, lab.app.widgets…)."""
    for key in list(sys.modules):
        if key in names or any(key.startswith(n + ".") for n in names):
            sys.modules.pop(key, None)


def _install_fake_winreg(state: dict) -> None:
    """winreg falso com estado mutável (preserva/reporta o que foi escrito)."""
    fake = types.ModuleType("winreg")
    fake.HKEY_CURRENT_USER = 0
    fake.KEY_READ = 0x20019
    fake.KEY_WRITE = 0x20006
    fake.REG_EXPAND_SZ = 2

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(root, sub, reserved=0, access=0):
        return _Key()

    def QueryValueEx(key, name):
        if state["missing"]:
            raise FileNotFoundError(name)
        return state["value"], state["vtype"]

    def SetValueEx(key, name, reserved=0, vtype=0, value=""):
        state["written"] = (vtype, value)
        state["value"], state["vtype"], state["missing"] = value, vtype, False

    fake.OpenKey = OpenKey
    fake.QueryValueEx = QueryValueEx
    fake.SetValueEx = SetValueEx
    sys.modules["winreg"] = fake


# ------------------------------------------------------------- import purity
def test_cli_import_is_posix_free():
    """Importar lab.cli não pode carregar a TUI nem o PTY (isso matava o Windows).

    Nota: 'fcntl' não entra na lista — no Linux ele é carregado por deps
    cross-platform (docker/psutil/textual) via imports guardados; o crash do
    Windows vinha do import NÃO guardado de ptyprocess.
    """
    probe = (
        "import sys, lab.cli;"
        "bad = [m for m in ('lab.app', 'lab.terminal', 'ptyprocess',"
        " 'pyte') if m in sys.modules];"
        "print('carregou:', bad); sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", probe], cwd=REPO,
                        capture_output=True, text=True, timeout=90)
    check("import da CLI não carrega módulos de TUI/PTY",
          r.returncode == 0, r.stdout.strip() or r.stderr.strip()[:80])


def test_cli_help_works():
    r = _run_cli(["--help"])
    check("--help funciona (rc 0 + usage)",
          r.returncode == 0 and "cyberlab_py" in r.stdout,
          (r.stdout or r.stderr).replace("\n", " ")[:80])


def test_cli_status_reports_daemon_not_fcntl():
    """--status/--setup/--audit só dependem do Docker SDK — nunca de fcntl."""
    r = _run_cli(["--status"])
    out = r.stdout + r.stderr
    ok = r.returncode in (0, 1) and "fcntl" not in out and "ModuleNotFoundError" not in out
    last = out.strip().splitlines()[-1] if out.strip() else "(sem saída)"
    check("--status sem crash POSIX (erro é do daemon, se houver)", ok, last)


# --------------------------------------------------- Terminal degrada com honestidade
def test_terminal_importable_without_ptyprocess():
    """ptyprocess ausente (Windows) não pode impedir o import do widget."""
    saved = sys.modules.get("ptyprocess")
    sys.modules.pop("lab.terminal", None)
    sys.modules["ptyprocess"] = None  # "import ptyprocess" passa a falhar
    try:
        import lab.terminal as tmod

        term = tmod.Terminal(["sh"])
        check("lab.terminal importável sem ptyprocess", True)
        check("widget Terminal constrói fora de um PTY", term is not None)
    except Exception as exc:
        check("lab.terminal importável sem ptyprocess", False, repr(exc))
    finally:
        sys.modules.pop("ptyprocess", None)
        _purge_module_tree("lab.terminal")
        import lab.terminal  # noqa: F401  — restaura o módulo real
        if saved is not None:
            sys.modules["ptyprocess"] = saved


def test_terminal_mount_reports_windows_limitation():
    """Painel de terminal sem PTY: mensagem informativa + não derruba a TUI."""
    saved_platform = sys.platform
    sys.modules.pop("lab.terminal", None)
    sys.modules["ptyprocess"] = None
    try:
        import lab.terminal as tmod

        term = tmod.Terminal(["docker", "exec", "-it", "x", "sh"])
        sys.platform = "win32"
        term.on_mount()
        shown = "\n".join(term._main_screen.display)
        check("on_mount sem PTY marca o painel como encerrado", term._dead)
        check("mensagem de falha visível no painel",
              "falha ao iniciar terminal" in shown, shown[:60])
        check("limitação do Windows nativo explicada",
              "Windows nativo" in shown and "WSL2" in shown)
        check("não simula PTY (nenhum processo criado)", term._proc is None)
    finally:
        sys.platform = saved_platform
        sys.modules.pop("ptyprocess", None)
        _purge_module_tree("lab.terminal")
        import lab.terminal  # noqa: F401  — restaura o módulo real


def test_app_degrades_without_terminal():
    """Sem lab.terminal a TUI sobe, informa a limitação e continua gerenciável."""
    for mod in ("lab.terminal", "lab.app"):
        sys.modules.pop(mod, None)
    sys.modules["pyte"] = None  # faz o import de lab.terminal falhar
    captured: list[str] = []
    try:
        import lab.app as appmod

        check("lab.app importável mesmo sem lab.terminal",
              appmod.Terminal is None)
        check("causa do fallback registrada (não engolida)",
              appmod._TERMINAL_IMPORT_ERROR is not None)

        async def scenario() -> bool:
            app = appmod.CyberLabApp()
            app._log = lambda msg: captured.append(msg)
            async with app.run_test(size=(120, 40)) as pilot:
                # docker ausente: setup falha, mas a TUI segue viva
                app.open_terminal("cyberlab-attacker", "/bin/bash", "atacante")
                await pilot.pause(0.5)
                ok_no_pane = "pane-cyberlab-attacker" not in app._open_panes
                await pilot.press("f2")   # alternar foco não pode quebrar
                await pilot.pause(0.2)
                return ok_no_pane

        ok_pane = asyncio.run(scenario())
        check("TUI viva; terminal não virou painel", ok_pane)
        check("limitação informada no log de eventos",
              any("terminais embutidos indisponíveis" in m for m in captured),
              captured[-1][:80] if captured else "(sem log)")
    except Exception as exc:
        check("TUI degrada sem lab.terminal", False, repr(exc))
    finally:
        # purga a árvore inteira: subentradas stale (pyte.screens…) fazem o
        # reimport parcial e quebram pyte.screens.Char no resto da suíte
        _purge_module_tree("pyte", "lab.terminal", "lab.app")
        import lab.terminal  # noqa: F401  — restaura módulos reais
        import lab.app  # noqa: F401


# ------------------------------------------------------------ _bin_dir por ambiente
def test_bin_dir_selection():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with _fake_home(tmp):
            check("POSIX: ~/.local/bin",
                  cli._bin_dir() == tmp / ".local" / "bin", str(cli._bin_dir()))

        old_platform = sys.platform
        old_in_venv = cli._in_venv
        import site

        saved_getuserbase = site.getuserbase
        old_prefix = sys.prefix
        try:
            sys.platform = "win32"
            # Python de sistema: caminho derivado do PRÓPRIO interpretador
            fake_userbase = r"C:\Users\fake\AppData\Roaming\Python"
            site.getuserbase = lambda: fake_userbase
            cli._in_venv = lambda: False
            got = cli._bin_dir()
            check("Win (Python de sistema): base de usuário via site.getuserbase",
                  got == Path(fake_userbase) / "Scripts", str(got))

            # venv/pipx: Scripts do próprio ambiente em uso
            fake_prefix = r"C:\venvs\cyberlab"
            sys.prefix = fake_prefix
            cli._in_venv = lambda: True
            got = cli._bin_dir()
            check("Win (venv): Scripts do ambiente em uso",
                  got == Path(fake_prefix) / "Scripts", str(got))
        finally:
            sys.platform = old_platform
            sys.prefix = old_prefix
            cli._in_venv = old_in_venv
            site.getuserbase = saved_getuserbase


# ------------------------------------------------------------ instalador
def test_install_posix_functional_and_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with _fake_home(tmp):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.cli_install()
            launcher = tmp / ".local" / "bin" / "cyberlab_py"
            check("install: rc 0 e launcher realmente criado",
                  rc == 0 and launcher.is_file(), out.getvalue().strip()[:80])
            content = launcher.read_text()
            check("launcher chama este Python com -m lab.cli",
                  sys.executable in content and "-m lab.cli" in content,
                  content.strip())
            # verificação FUNCIONAL: rodar o launcher de verdade
            env = dict(os.environ)
            env["PYTHONPATH"] = str(REPO)
            r = subprocess.run(["sh", str(launcher), "--help"], cwd=REPO, env=env,
                               capture_output=True, text=True, timeout=90)
            check("launcher executável funciona (sh launcher --help)",
                  r.returncode == 0 and "cyberlab_py" in r.stdout,
                  (r.stderr or r.stdout).replace("\n", " ")[:80])
            with contextlib.redirect_stdout(io.StringIO()):
                rc2 = cli.cli_install()
            check("install é idempotente (reinstalar não falha)",
                  rc2 == 0 and launcher.is_file())
            with contextlib.redirect_stdout(io.StringIO()):
                rmu = cli.cli_uninstall()
            check("uninstall remove o launcher", rmu == 0 and not launcher.exists())
            out2 = io.StringIO()
            with contextlib.redirect_stdout(out2):
                rmu2 = cli.cli_uninstall()
            check("uninstall repetido é inofensivo",
                  rmu2 == 0 and "não estava instalado" in out2.getvalue())


def test_install_windows_writes_cmd_and_uninstall():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        old_platform, old_bindir, old_invenv = (
            sys.platform, cli._bin_dir, cli._in_venv,
        )
        sys.platform = "win32"
        cli._bin_dir = lambda: tmp / "bin"
        cli._in_venv = lambda: False
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = cli.cli_install()
            launcher = tmp / "bin" / "cyberlab_py.cmd"
            check("Windows: rc 0 e .cmd criado", rc == 0 and launcher.is_file())
            raw = launcher.read_bytes()
            check(".cmd com CRLF intactos (sem \\r\\r\\n)",
                  b"\r\r\n" not in raw and raw.startswith(b"@echo off\r\n"),
                  repr(raw[:40]))
            check(".cmd referencia -m lab.cli", b"-m lab.cli" in raw)
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                rmu = cli.cli_uninstall()
            check("Windows: uninstall remove o .cmd",
                  rmu == 0 and not launcher.exists())
        finally:
            sys.platform = old_platform
            cli._bin_dir, cli._in_venv = old_bindir, old_invenv


def test_install_failure_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        blocked = tmp / "blocked"
        blocked.write_text("sou um arquivo, não um diretório")
        old_bindir = cli._bin_dir
        cli._bin_dir = lambda: blocked / "bin"
        try:
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(err):
                rc = cli.cli_install()
            check("falha de criação -> rc 1 (sem falso sucesso)", rc == 1)
            check("erro explícito no stderr (não engolido)",
                  "ERRO" in err.getvalue(), err.getvalue().strip()[:80])
        finally:
            cli._bin_dir = old_bindir


def test_windows_add_user_path_preserves_entries():
    state = {"value": r"C:\tools", "vtype": 2, "missing": False, "written": None}
    old_platform = sys.platform
    old_pathsep = os.pathsep
    sys.platform = "win32"
    os.pathsep = ";"  # semântica real do Windows (":" quebraria drive letters)
    _install_fake_winreg(state)
    try:
        ok1 = cli._windows_add_user_path(Path(r"C:\cyberlab\bin"))
        written = state["written"]
        check("PATH do usuário editado via registro", ok1 and written is not None)
        if written:
            parts = written[1].split(os.pathsep)
            check("entrada existente preservada", r"C:\tools" in parts, written[1])
            check("novo diretório appended", r"C:\cyberlab\bin" in parts, written[1])
        state["written"] = None
        ok2 = cli._windows_add_user_path(Path(r"C:\cyberlab\bin"))
        check("idempotente: já presente no PATH não reescreve",
              ok2 and state["written"] is None)
        state.update(missing=True, written=None, value=None, vtype=None)
        ok3 = cli._windows_add_user_path(Path(r"C:\isolated\bin"))
        check("sem PATH prévio: cria limpo (só o novo diretório)",
              ok3 and state["written"] is not None
              and state["written"][1] == r"C:\isolated\bin",
              str(state["written"]))
    finally:
        sys.platform = old_platform
        os.pathsep = old_pathsep
        sys.modules.pop("winreg", None)


def test_install_in_venv_skips_registry_path():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        state = {"value": r"C:\tools", "vtype": 2, "missing": False, "written": None}
        old_platform, old_bindir, old_invenv = (
            sys.platform, cli._bin_dir, cli._in_venv,
        )
        sys.platform = "win32"
        cli._bin_dir = lambda: tmp / "bin"
        cli._in_venv = lambda: True
        _install_fake_winreg(state)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = cli.cli_install()
            check("venv: launcher criado no Scripts do venv",
                  rc == 0 and (tmp / "bin" / "cyberlab_py.cmd").is_file())
            check("venv: registro do PATH do usuário NÃO é tocado",
                  state["written"] is None)
            check("venv: mensagem orienta usar o venv ativado",
                  "venv" in out.getvalue() or "ambiente virtual" in out.getvalue(),
                  out.getvalue().strip()[-90:])
        finally:
            sys.platform = old_platform
            cli._bin_dir, cli._in_venv = old_bindir, old_invenv
            sys.modules.pop("winreg", None)


def main() -> int:
    for fn in (
        test_cli_import_is_posix_free,
        test_cli_help_works,
        test_cli_status_reports_daemon_not_fcntl,
        test_terminal_importable_without_ptyprocess,
        test_terminal_mount_reports_windows_limitation,
        test_app_degrades_without_terminal,
        test_bin_dir_selection,
        test_install_posix_functional_and_idempotent,
        test_install_windows_writes_cmd_and_uninstall,
        test_install_failure_is_reported,
        test_windows_add_user_path_preserves_entries,
        test_install_in_venv_skips_registry_path,
    ):
        try:
            fn()
        except AssertionError as exc:
            check(f"{fn.__name__} quebrou: {exc}", False)
        except Exception as exc:  # falha dura = FAIL, não crash
            check(f"{fn.__name__} explodiu: {exc!r}", False)
    print(f"\n{sum(CHECKS)}/{len(CHECKS)} verificações passaram")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
