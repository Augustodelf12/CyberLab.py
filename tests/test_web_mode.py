#!/usr/bin/env python3
"""
Testes de regressão do MODO WEB (CYBERLAB_WEB_MODE=1) — sem Docker, com
stubs do SDK (rodam em qualquer máquina/CI):

    python tests/test_web_mode.py
    pytest tests/test_web_mode.py -q

Cobrem o bloqueio pedido: no modo web do site, apenas o atacante e o
webvuln-1 podem existir; os demais alvos (shopvuln/privesc/sshweak/ftpanon),
target add e tool add/run são recusados com a mensagem de instalar o app.
Fora do modo web, nada muda (bloqueio não pode vazar para o uso normal).
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lab.manager as mgmt  # noqa: E402
from lab.manager import ATTACKER_NAME, NETWORK_NAME, LabError, LabManager  # noqa: E402

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ------------------------------------------------------------- stubs (SDK)
class FakeNet:
    def __init__(self):
        self.attrs = {"Internal": True}

    def connect(self, name): pass

    def disconnect(self, name, force=False): pass


class FakeCreated:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True


class FakeNetworks:
    def get(self, name):
        if name in (NETWORK_NAME, "bridge"):
            return FakeNet()
        raise mgmt.NotFound(name)

    def list(self, names=None):
        return []

    def create(self, *a, **kw):
        return FakeNet()


class FakeContainers:
    def list(self, all=True, filters=None):
        return []

    def get(self, name):
        raise mgmt.NotFound(name)

    def create(self, *a, **kw):
        return FakeCreated()


class FakeImages:
    def get(self, tag):
        raise mgmt.ImageNotFound(tag)

    def build(self, *a, **kw):
        return object(), []

    def remove(self, tag, force=False):
        pass


class FakeClient:
    def __init__(self):
        self.networks = FakeNetworks()
        self.containers = FakeContainers()
        self.images = FakeImages()

    def ping(self):
        return True


def make_manager() -> LabManager:
    m = LabManager()
    m._client = FakeClient()
    return m


def with_temp_registry(fn):
    old_reg, old_tools = mgmt.REGISTRY_PATH, mgmt.TOOLS_DIR
    with tempfile.TemporaryDirectory(prefix="cyberlab-web-") as tmp:
        tmp = Path(tmp)
        tools = tmp / "tools"
        tools.mkdir()
        mgmt.TOOLS_DIR = tools
        mgmt.REGISTRY_PATH = tmp / "registry.json"
        try:
            fn(tmp, tools)
        finally:
            mgmt.REGISTRY_PATH, mgmt.TOOLS_DIR = old_reg, old_tools


# ------------------------------------------------------------------ tests
def test_web_mode_blocks_other_vms():
    """shopvuln/privesc/sshweak/ftpanon recusados com a mensagem do app."""
    old = mgmt.WEB_MODE
    mgmt.WEB_MODE = True
    try:
        m = make_manager()
        for kind in ("shopvuln", "privesc", "sshweak", "ftpanon"):
            try:
                m.spawn_target(kind)
                check(f"web: spawn {kind} recusado", False, "não levantou LabError")
            except LabError as exc:
                ok = "app completo" in str(exc) and "app completo" in str(exc) and kind in str(exc)
                check(f"web: spawn {kind} recusado (msg do app)", ok, str(exc))
    finally:
        mgmt.WEB_MODE = old


def test_web_mode_allows_webvuln():
    """webvuln-1 continua spawnável no modo web (única VM web de alvo)."""
    old = mgmt.WEB_MODE
    mgmt.WEB_MODE = True
    try:
        m = make_manager()

        def scenario(tmp, tools):
            m.spawn_target("webvuln")
            check("web: spawn webvuln permitido (nome correto)", True)
        with_temp_registry(scenario)
    finally:
        mgmt.WEB_MODE = old


def test_normal_mode_allows_everything():
    """Sem o modo web, TODOS os alvos continuam permitidos (sem vazamento)."""
    old = mgmt.WEB_MODE
    mgmt.WEB_MODE = False
    try:
        def scenario(tmp, tools):
            m = make_manager()
            for kind in ("shopvuln", "privesc", "sshweak", "ftpanon"):
                m.spawn_target(kind)  # não pode levantar LabError
            check("normal: todos os alvos permitidos fora do modo web", True)
        with_temp_registry(scenario)
    finally:
        mgmt.WEB_MODE = old


def test_web_mode_blocks_custom_targets_and_tools():
    """target add / tool add / tool run recusados no modo web."""
    old = mgmt.WEB_MODE
    mgmt.WEB_MODE = True
    try:
        def scenario(tmp, tools):
            m = make_manager()
            ctx = tmp / "meu-alvo"
            ctx.mkdir()
            (ctx / "Dockerfile").write_text("FROM alpine\n")
            for label, call in (
                ("target add", lambda: m.add_target(str(ctx))),
                ("tool add", lambda: m.add_tool(str(ctx))),
                ("tool run", lambda: m.run_tool("x", [])),
            ):
                try:
                    call()
                    check(f"web: {label} recusado", False, "não levantou LabError")
                except LabError as exc:
                    check(f"web: {label} recusado (msg do app)", "app completo" in str(exc), str(exc))
            reg = json.loads(mgmt.REGISTRY_PATH.read_text()) if mgmt.REGISTRY_PATH.exists() else {}
            check("web: registry permanece vazio", not reg, str(reg))
        with_temp_registry(scenario)
    finally:
        mgmt.WEB_MODE = old


def test_normal_mode_custom_still_works():
    """Fora do modo web, target add continua funcionando (com Dockerfile válido)."""
    old = mgmt.WEB_MODE
    mgmt.WEB_MODE = False
    try:
        def scenario(tmp, tools):
            m = make_manager()
            ctx = tmp / "alvo-ok"
            ctx.mkdir()
            (ctx / "Dockerfile").write_text("FROM alpine\n")
            name = m.add_target(str(ctx))
            check("normal: target add fora do modo web", name == "alvo-ok", name)
            reg = json.loads(mgmt.REGISTRY_PATH.read_text())
            check("normal: registry registra o custom", "alvo-ok" in reg.get("targets", {}))
        with_temp_registry(scenario)
    finally:
        mgmt.WEB_MODE = old


def main() -> int:
    for fn in (
        test_web_mode_blocks_other_vms,
        test_web_mode_allows_webvuln,
        test_normal_mode_allows_everything,
        test_web_mode_blocks_custom_targets_and_tools,
        test_normal_mode_custom_still_works,
    ):
        try:
            fn()
        except AssertionError as exc:
            check(f"{fn.__name__} quebrou: {exc}", False)
        except Exception as exc:
            check(f"{fn.__name__} explodiu: {exc!r}", False)
    print(f"\n{sum(CHECKS)}/{len(CHECKS)} verificações passaram")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
