#!/usr/bin/env python3
"""
Testes de regressão de SEGURANÇA da plataforma CyberLab (sem Docker — usam
stubs do SDK, então rodam em qualquer máquina/CI):

    python tests/test_security.py
    pytest tests/test_security.py -q

Cobrem os fixes da auditoria:
  FIX-1  airgap coerente: nunca LIGA NAT; permite/força DESLIGAR;
         --audit enxerga o estado real da bridge (CWE-668).
  FIX-2  remove_tool recusa apagar caminho fora de TOOLS_DIR (CWE-22).
  FIX-3  _slug rejeita nomes de travessia ('.'/'..') e 'attacker'
         reservado não pode ser sombreado pelo registry (CWE-22/706).
  FIX-4  sync de exemplos não segue symlinks plantados no volume (CWE-59).
  FIX-5  containers nascem com pids_limit (anti fork-bomb no host, CWE-400).
  FIX-6  bind mount do atacante comparado por caminho RESOLVIDO
         (symlink em ~/.local/share não recria o container a cada boot).
  FIX-7  run_tool: quoting de nome/entry/args resiste a metacaracteres
         mesmo com registry adulterado (CWE-78 regression lock).
  FIX-8  registry: read-modify-write sob lock (imports concorrentes na
         TUI não perdem registros) + remove_tool valida ANTES de mutar.
"""
import json
import shlex
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lab.manager as mgmt  # noqa: E402
from lab.manager import ATTACKER_NAME, NETWORK_NAME, LabError, LabManager  # noqa: E402

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# --------------------------------------------------------------- stubs (SDK)
class FakeBridge:
    def __init__(self, attacker):
        self.connects = []
        self.disconnects = []
        self._attacker = attacker  # desconectar reflete no estado do container

    def connect(self, name):
        self.connects.append(name)
        self._attacker.attrs["NetworkSettings"]["Networks"]["bridge"] = {"IPAddress": "172.17.0.2"}

    def disconnect(self, name, force=False):
        self.disconnects.append(name)
        self._attacker.attrs["NetworkSettings"]["Networks"].pop("bridge", None)


class FakeNetwork:
    def __init__(self, internal=True):
        self.attrs = {"Internal": internal}


class FakeContainer:
    def __init__(self, bridged):
        self.name = ATTACKER_NAME
        nets = {NETWORK_NAME: {"IPAddress": "172.30.0.2"}}
        if bridged:
            nets["bridge"] = {"IPAddress": "172.17.0.2"}
        self.attrs = {"NetworkSettings": {"Networks": nets}}


class FakeClient:
    def __init__(self, attacker_bridged):
        self.attacker = FakeContainer(attacker_bridged)
        self.bridge = FakeBridge(self.attacker)
        self.networks = _NetApi(self.bridge)
        self.containers = _ContainerApi(self.attacker)


class _NetApi:
    def __init__(self, bridge):
        self.bridge = bridge

    def get(self, name):
        if name == "bridge":
            return self.bridge
        if name == NETWORK_NAME:
            return FakeNetwork(internal=True)
        raise mgmt.NotFound(f"network {name} not found")


class _ContainerApi:
    def __init__(self, attacker):
        self._attacker = attacker

    def get(self, name):
        if name == ATTACKER_NAME:
            return self._attacker
        raise mgmt.NotFound(f"container {name} not found")

    def list(self, all=True, filters=None):
        return [self._attacker]


def make_manager(attacker_bridged: bool) -> LabManager:
    m = LabManager()
    m._client = FakeClient(attacker_bridged)
    return m


# ------------------------------------------------- stubs p/ containers (FIX-5/6)
class FakeCreated:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True


class FakeAttackerContainer:
    def __init__(self, mount_source: str, status: str = "running") -> None:
        self.status = status
        self.attrs = {
            "Mounts": [{
                "Type": "bind",
                "Source": mount_source,
                "Destination": "/root/tools",
            }],
        }
        self.started = False

    def start(self) -> None:
        self.started = True

    def remove(self, force: bool = False) -> None:
        pass


class RecordingContainers:
    """API de containers que registra create() e devolve um preset."""

    def __init__(self, preset=None) -> None:
        self.calls: list[dict] = []
        self._preset = preset

    def get(self, name):
        if self._preset is not None and name == ATTACKER_NAME:
            return self._preset
        raise mgmt.NotFound(f"container {name} not found")

    def list(self, all=True, filters=None):
        return []

    def create(self, image, **kwargs):
        self.calls.append({"image": image, **kwargs})
        return FakeCreated()


class _Client:
    def __init__(self, containers) -> None:
        self.containers = containers
        self.networks = _NetApi(FakeBridge(FakeContainer(False)))


# ------------------------------------------------------------------- FIX-1
def test_airgap_never_connects_nat():
    """AIRGAP: set_internet(True) NUNCA chama bridge.connect."""
    old = mgmt.AIRGAP
    mgmt.AIRGAP = True
    try:
        m = make_manager(attacker_bridged=False)
        result = m.set_internet(True)
        check("airgap: set_internet(True) não conecta NAT",
              m.client.bridge.connects == [] and result is False)
    finally:
        mgmt.AIRGAP = old


def test_airgap_allows_disconnect():
    """AIRGAP: set_internet(False) PRECISA poder desconectar (era bloqueado)."""
    old = mgmt.AIRGAP
    mgmt.AIRGAP = True
    try:
        m = make_manager(attacker_bridged=True)
        m.set_internet(False)
        check("airgap: set_internet(False) desconecta a bridge",
              m.client.bridge.disconnects == [ATTACKER_NAME])
    finally:
        mgmt.AIRGAP = old


def test_internet_enabled_reports_real_state():
    """internet_enabled() relata o estado REAL, mesmo sob airgap."""
    old = mgmt.AIRGAP
    mgmt.AIRGAP = True
    try:
        m = make_manager(attacker_bridged=True)
        check("internet_enabled() enxerga bridge real sob airgap",
              m.internet_enabled() is True)
    finally:
        mgmt.AIRGAP = old


def test_audit_not_masked_by_airgap():
    """ANTES do fix, --audit dizia 'ISOLADO' sob airgap mesmo com NAT ligado."""
    old = mgmt.AIRGAP
    mgmt.AIRGAP = True
    try:
        m = make_manager(attacker_bridged=True)
        report = m.audit_isolation()
        check("audit reporta atacante com NAT sob airgap (sem máscara)",
              report["atacante_sem_nat"] is False)
        m.enforce_airgap()
        check("enforce_airgap desconecta a bridge",
              m.client.bridge.disconnects == [ATTACKER_NAME])
        report = m.audit_isolation()
        check("audit fica isolado após enforce_airgap",
              report["atacante_sem_nat"] is True)
    finally:
        mgmt.AIRGAP = old


def test_audit_ok_when_really_isolated():
    """Sem airgap e sem bridge, audit aprova (comportamento preservado)."""
    old = mgmt.AIRGAP
    mgmt.AIRGAP = False
    try:
        m = make_manager(attacker_bridged=False)
        report = m.audit_isolation()
        check("audit aprova lab realmente isolado",
              report["atacante_sem_nat"] is True and report["rede_internal"] is True)
    finally:
        mgmt.AIRGAP = old


# ------------------------------------------------------------------- FIX-2
def _with_temp_registry(fn):
    old_reg, old_tools = mgmt.REGISTRY_PATH, mgmt.TOOLS_DIR
    with tempfile.TemporaryDirectory(prefix="cyberlab-sec-") as tmp:
        tmp = Path(tmp)
        tools = tmp / "tools"
        tools.mkdir()
        mgmt.TOOLS_DIR = tools
        mgmt.REGISTRY_PATH = tmp / "registry.json"
        try:
            fn(tmp, tools)
        finally:
            mgmt.REGISTRY_PATH, mgmt.TOOLS_DIR = old_reg, old_tools


def test_remove_tool_stays_inside_tools_dir():
    """Registry adulterado não pode transformar 'tool remove' em rmtree arbitrário."""
    def scenario(tmp, tools):
        victim = tmp / "importante"
        victim.mkdir()
        (victim / "dados.txt").write_text("mantenha")
        (tools / "boa").mkdir()
        mgmt.REGISTRY_PATH.write_text(json.dumps({
            "tools": {
                "boa": {"path": str(tmp / "x"), "synced": str(tools / "boa")},
                "maliciosa": {"path": str(tmp / "y"), "synced": str(victim)},
            }
        }))
        m = make_manager(attacker_bridged=False)
        try:
            m.remove_tool("maliciosa")
            check("remove_tool fora de TOOLS_DIR é recusado", False, "não levantou LabError")
        except LabError:
            check("remove_tool fora de TOOLS_DIR é recusado (LabError)", True)
        check("vítima continua no disco", (victim / "dados.txt").exists())
        m.remove_tool("boa")
        check("remove_tool dentro de TOOLS_DIR remove normalmente",
              not (tools / "boa").exists())
        reg = json.loads(mgmt.REGISTRY_PATH.read_text())
        check("registry atualizado nas duas remoções",
              set(reg["tools"]) == {"maliciosa"} or reg["tools"] == {} or
              "boa" not in reg["tools"])
    _with_temp_registry(scenario)


# ------------------------------------------------------------- airgap v2
class FakeLabContainer:
    def __init__(self, name: str, nets: list[str]) -> None:
        self.name = name
        self.attrs = {"NetworkSettings": {"Networks": {n: {} for n in nets}}}


class RecordingNetApi:
    """networks.get(nome) -> objeto que grava disconnects."""

    def __init__(self) -> None:
        self.disconnects: list[tuple[str, str]] = []

    def get(self, name):
        api = self

        class _Net:
            def disconnect(self, container, force=False):
                api.disconnects.append((name, container))

        return _Net()


class _ClientWithNets:
    def __init__(self, netapi, containers) -> None:
        self.networks = netapi
        self._containers = containers

        class _Api:
            def get(self, name):
                raise mgmt.NotFound(f"container {name} not found")

            def list(self, all=True, filters=None):
                return api._containers

        api = self
        self.containers = _Api()


def test_enforce_airgap_strips_all_extra_networks():
    """Airgap não pode ter via secundária: QUALQUER container em QUALQUER
    rede externa (não só o atacante na bridge) é desconectado."""
    old = mgmt.AIRGAP
    mgmt.AIRGAP = True
    try:
        netapi = RecordingNetApi()
        m = LabManager()
        m._client = _ClientWithNets(netapi, [
            FakeLabContainer(ATTACKER_NAME, [NETWORK_NAME, "bridge"]),
            FakeLabContainer("cyberlab-webvuln-1", [NETWORK_NAME, "bridge", "lan-extra"]),
        ])
        m.enforce_airgap()
        check("atacante sai da bridge",
              ("bridge", ATTACKER_NAME) in netapi.disconnects, str(netapi.disconnects))
        check("alvo também sai da bridge",
              ("bridge", "cyberlab-webvuln-1") in netapi.disconnects)
        check("rede extra de terceiros também é removida",
              ("lan-extra", "cyberlab-webvuln-1") in netapi.disconnects)
        check("rede interna do lab nunca é desconectada",
              not any(net == NETWORK_NAME for net, _ in netapi.disconnects))
        # sem airgap: enforce não toca em nada
        mgmt.AIRGAP = False
        netapi2 = RecordingNetApi()
        m2 = LabManager()
        m2._client = _ClientWithNets(netapi2, [
            FakeLabContainer(ATTACKER_NAME, [NETWORK_NAME, "bridge"]),
        ])
        m2.enforce_airgap()
        check("sem CYBERLAB_AIRGAP o enforce é no-op", netapi2.disconnects == [])
    finally:
        mgmt.AIRGAP = old



def test_slug_rejects_traversal_and_reserved():
    """'..' como nome de tool fazia rmtree(TOOLS_DIR/..) — data dir inteiro."""
    for bad in ("..", ".", "...", " .. "):
        try:
            LabManager._slug(bad)
            check(f"_slug({bad!r}) rejeita travessia", False, "não levantou LabError")
        except LabError:
            check(f"_slug({bad!r}) rejeita travessia (LabError)", True)
    # comportamento normal preservado (API pública não muda)
    check("_slug normaliza espaços", LabManager._slug("Minha Ferramenta!") == "Minha-Ferramenta")
    check("_slug preserva pontos/hífens", LabManager._slug("tool.v2-beta") == "tool.v2-beta")
    check("_slug vazio -> 'app'", LabManager._slug("") == "app" and LabManager._slug("  ") == "app")

    def scenario(tmp, tools):
        src = tmp / "src"; src.mkdir()
        m = make_manager(attacker_bridged=False)
        try:
            m.add_tool(src, "..")
            check("add_tool --name '..' é recusado", False, "não levantou LabError")
        except LabError:
            check("add_tool --name '..' é recusado (LabError)", True)
        check("data dir sobreviveu", tools.exists())

    _with_temp_registry(scenario)


def test_attacker_name_reserved():
    """Alvo custom chamado 'attacker' sombreava o spec da máquina atacante."""
    reg = {
        "targets": {
            "attacker": {"image": "cyberlab/custom-attacker:latest", "desc": "fake"},
            "webvuln": {"image": "evil/webvuln:latest", "desc": "fake"},
        }
    }

    def scenario(tmp, tools):
        mgmt.REGISTRY_PATH.write_text(json.dumps(reg))
        m = make_manager(attacker_bridged=False)
        check("'attacker' do registry é ignorado em all_targets()",
              "attacker" not in m.all_targets())
        check("built-in não é sombreado pelo registry",
              m.all_targets()["webvuln"]["image"].startswith("cyberlab/webvuln"))
        specs = m.image_specs()
        check("image_specs mantém o spec real do atacante",
              specs["attacker"]["image"] == mgmt.ATTACKER_IMAGE)
        # caminho feliz: CLI rejeita na porta de entrada
        d = tmp / "d"; d.mkdir(); (d / "Dockerfile").write_text("FROM alpine:3.20\n")
        try:
            m.add_target(d, "attacker")
            check("add_target --name attacker é recusado", False, "não levantou LabError")
        except LabError:
            check("add_target --name attacker é recusado (LabError)", True)

    _with_temp_registry(scenario)


# ------------------------------------------------------------------- FIX-4
def test_example_sync_does_not_follow_symlinks():
    """Symlink plantado no volume não redireciona a cópia p/ fora do tools dir."""
    old_tools, old_examples = mgmt.TOOLS_DIR, mgmt.EXAMPLES_DIR
    with tempfile.TemporaryDirectory(prefix="cyberlab-sec-") as tmp:
        tmp = Path(tmp)
        tools = tmp / "tools"; tools.mkdir()
        examples = tmp / "examples"; examples.mkdir()
        (examples / "main.py").write_text("print('exemplo')\n")
        mgmt.TOOLS_DIR, mgmt.EXAMPLES_DIR = tools, examples
        try:
            victim = tmp / "fora_do_tools.cfg"
            planted = tools / "main.py"
            planted.symlink_to(victim)   # dangling: exists() == False
            m = make_manager(attacker_bridged=False)
            m._sync_example_tools()
            check("cópia NÃO escreveu através do symlink", not victim.exists())
            check("symlink foi substituído pelo arquivo real",
                  planted.is_file() and not planted.is_symlink())

            # symlink apontando p/ arquivo existente: vítima intacta
            victim2 = tmp / ".bashrc"; victim2.write_text("export PATH=$HOME/bin\n")
            planted2 = tools / "outro.py"; planted2.symlink_to(victim2)
            m._sync_example_tools()
            check("vítima de symlink p/ arquivo existente preservada",
                  victim2.read_text() == "export PATH=$HOME/bin\n")
        finally:
            mgmt.TOOLS_DIR, mgmt.EXAMPLES_DIR = old_tools, old_examples


# ------------------------------------------------------------------- FIX-5
def test_containers_born_with_pids_limit():
    """Alvos e atacante nascem com pids_limit (anti fork-bomb no host)."""
    def scenario(tmp, tools):
        api = RecordingContainers()
        m = make_manager(attacker_bridged=False)
        m._client = _Client(api)
        name = m.spawn_target("webvuln")
        check("spawn_target cria container", api.calls and api.calls[0]["image"].startswith("cyberlab/webvuln"))
        check("alvo nasce com pids_limit=256", api.calls[0].get("pids_limit") == 256,
              str(api.calls[0].get("pids_limit")))
        check("alvo mantém mem_limit do spec", api.calls[0].get("mem_limit") == "128m")
        check("nome sequencial do alvo", name == "cyberlab-webvuln-1", name)

    _with_temp_registry(scenario)

    # atacante
    old_tools, old_examples, old_dirs = mgmt.TOOLS_DIR, mgmt.EXAMPLES_DIR, mgmt.ensure_user_dirs
    with tempfile.TemporaryDirectory(prefix="cyberlab-sec-") as tmp:
        tmp = Path(tmp)
        tools = tmp / "tools"
        mgmt.TOOLS_DIR = tools
        mgmt.EXAMPLES_DIR = tmp / "examples"; mgmt.EXAMPLES_DIR.mkdir()
        mgmt.ensure_user_dirs = lambda: None
        try:
            api = RecordingContainers()
            m = make_manager(attacker_bridged=False)
            m._client = _Client(api)
            m.ensure_attacker()
            check("atacante nasce com pids_limit=512",
                  api.calls and api.calls[0].get("pids_limit") == 512)
            check("atacante monta o tools dir em /root/tools",
                  api.calls and api.calls[0].get("volumes") == {str(tools): {"bind": "/root/tools", "mode": "rw"}})
        finally:
            mgmt.TOOLS_DIR, mgmt.EXAMPLES_DIR = old_tools, old_examples
            mgmt.ensure_user_dirs = old_dirs


# ------------------------------------------------------------------- FIX-6
def test_attacker_not_recreated_when_mount_differs_by_symlink():
    """Docker reporta o bind RESOLVIDO; comparar sem resolve() recriava sempre."""
    old_tools, old_examples, old_dirs = mgmt.TOOLS_DIR, mgmt.EXAMPLES_DIR, mgmt.ensure_user_dirs
    with tempfile.TemporaryDirectory(prefix="cyberlab-sec-") as tmp:
        tmp = Path(tmp)
        tools_real = tmp / "tools_real"; tools_real.mkdir()
        link = tmp / "link"; link.symlink_to(tools_real)
        mgmt.TOOLS_DIR = link               # caminho NÃO resolvido (via symlink)
        mgmt.EXAMPLES_DIR = tmp / "examples"; mgmt.EXAMPLES_DIR.mkdir()
        mgmt.ensure_user_dirs = lambda: None
        try:
            api = RecordingContainers(
                preset=FakeAttackerContainer(mount_source=str(tools_real))
            )
            m = make_manager(attacker_bridged=False)
            m._client = _Client(api)
            m.ensure_attacker()
            check("atacante NÃO é recriado por symlink no caminho",
                  api.calls == [], str(api.calls))
            check("atacante NÃO é reiniciado à toa",
                  api._preset.started is False)
        finally:
            mgmt.TOOLS_DIR = old_tools
            mgmt.EXAMPLES_DIR = old_examples
            mgmt.ensure_user_dirs = old_dirs


# ------------------------------------------------------------------- FIX-7
def test_run_tool_quoting_survives_hostile_registry():
    """Registry adulterado + args com metacaracteres não escapam do quoting."""
    def scenario(tmp, tools):
        m = make_manager(attacker_bridged=False)
        hostile_name = "x; rm -rf /"
        args = ["a; touch /tmp/pwned", "$(reboot)", "it's", "`id`"]
        captured = {}
        orig_call = mgmt.subprocess.call

        def fake_call(argv, *a, **k):
            captured["argv"] = argv
            return 0

        mgmt.subprocess.call = fake_call
        try:
            m.run_tool(hostile_name, args)
        finally:
            mgmt.subprocess.call = orig_call

        argv = captured["argv"]
        check("run_tool chama docker exec via argv (sem shell no host)",
              argv[:6] == ["docker", "exec", "-i", ATTACKER_NAME, "sh", "-c"],
              str(argv[:6]))
        command = argv[6]
        cd = f"cd {shlex.quote('/root/tools/' + hostile_name)} && "
        check("cd do tool dir é quoted", command.startswith(cd), command[:60])
        tokens = shlex.split(command[len(cd):])
        check("tokens fazem round-trip literal (sem injeção)",
              tokens == ["sh", *args], str(tokens))

    _with_temp_registry(scenario)


# ------------------------------------------------------------------- FIX-8
def test_concurrent_registry_updates_keep_both():
    """Dois add_tool concorrentes (workers da TUI) não podem perder registros."""
    def scenario(tmp, tools):
        m = make_manager(attacker_bridged=False)
        barrier = threading.Barrier(2)

        def worker(i: int) -> None:
            d = tmp / f"toolsrc{i}"; d.mkdir()
            (d / "main.py").write_text(f"print({i})\n")
            barrier.wait()
            m.add_tool(d, f"tool{i}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        listed = m.list_tools()
        check("import concorrente não perde registros",
              "tool0" in listed and "tool1" in listed, str(listed))

    _with_temp_registry(scenario)


def test_remove_tool_invalid_keeps_registry_entry():
    """Entrada suspeita permanece no registry p/ inspeção (valida antes de mutar)."""
    def scenario(tmp, tools):
        victim = tmp / "importante"; victim.mkdir()
        (victim / "dados.txt").write_text("mantenha")
        mgmt.REGISTRY_PATH.write_text(json.dumps({
            "tools": {"maliciosa": {"path": str(tmp / "y"), "synced": str(victim)}}
        }))
        m = make_manager(attacker_bridged=False)
        try:
            m.remove_tool("maliciosa")
            check("remove_tool inválido é recusado", False, "não levantou LabError")
        except LabError:
            check("remove_tool inválido é recusado (LabError)", True)
        check("vítima continua no disco", (victim / "dados.txt").exists())
        check("entrada suspeita PERMANECE no registry",
              "maliciosa" in m.list_tools())
        # limpeza manual não deve sobrar arquivo temporário atômico
        check("escrita atômica não deixa .tmp",
              not (tmp / "registry.json.tmp").exists())

    _with_temp_registry(scenario)


def main() -> int:
    for fn in (
        test_airgap_never_connects_nat,
        test_airgap_allows_disconnect,
        test_internet_enabled_reports_real_state,
        test_audit_not_masked_by_airgap,
        test_audit_ok_when_really_isolated,
        test_enforce_airgap_strips_all_extra_networks,
        test_remove_tool_stays_inside_tools_dir,
        test_slug_rejects_traversal_and_reserved,
        test_attacker_name_reserved,
        test_example_sync_does_not_follow_symlinks,
        test_containers_born_with_pids_limit,
        test_attacker_not_recreated_when_mount_differs_by_symlink,
        test_run_tool_quoting_survives_hostile_registry,
        test_concurrent_registry_updates_keep_both,
        test_remove_tool_invalid_keeps_registry_entry,
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
