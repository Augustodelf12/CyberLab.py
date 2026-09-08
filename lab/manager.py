"""
Gerenciador do CyberLab: rede isolada, imagens, containers e métricas.

Usa apenas o Docker SDK — sem docker-compose — para permitir criar/destruir
máquinas dinamicamente a partir da TUI.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import docker
import psutil
from docker.errors import APIError, ImageNotFound, NotFound

BASE_DIR = Path(__file__).resolve().parent.parent
DOCKER_DIR = BASE_DIR / "docker"
TOOLS_DIR = BASE_DIR / "tools"
REGISTRY_PATH = BASE_DIR / "registry.json"

NETWORK_NAME = "cyberlab-net"
SUBNET = "172.30.0.0/24"
GATEWAY = "172.30.0.1"

LABEL = "cyberlab"                # label para identificar tudo que é do lab
ATTACKER_NAME = "cyberlab-attacker"
ATTACKER_IMAGE = "cyberlab/attacker:latest"

# Tipos de alvo disponíveis para spawn
TARGETS: dict[str, dict] = {
    "webvuln": {
        "image": "cyberlab/webvuln:latest",
        "desc": "Web app vulnerável (SQLi, XSS, LFI, cmd injection)",
        "services": "HTTP :80",
        "mem_limit": "128m",
        "context": DOCKER_DIR / "webvuln",
        "dockerfile": "Dockerfile",
    },
    "sshweak": {
        "image": "cyberlab/sshweak:latest",
        "desc": "SSH com senhas fracas (root:toor, admin:admin, ...)",
        "services": "SSH :22",
        "mem_limit": "64m",
        "context": DOCKER_DIR,
        "dockerfile": "sshweak.Dockerfile",
    },
    "ftpanon": {
        "image": "cyberlab/ftpanon:latest",
        "desc": "FTP anônimo com arquivos sensíveis",
        "services": "FTP :21",
        "mem_limit": "64m",
        "context": DOCKER_DIR / "ftpanon",
        "dockerfile": "Dockerfile",
    },
}

ATTACKER_SPEC = {
    "image": ATTACKER_IMAGE,
    "context": DOCKER_DIR,
    "dockerfile": "attacker.Dockerfile",
}


@dataclass
class Machine:
    """Estado instantâneo de uma máquina do lab."""

    name: str
    kind: str           # attacker | webvuln | sshweak | ftpanon
    status: str         # running | exited | ...
    ip: str
    cpu: float = 0.0    # % de CPU (0-100+ por núcleo)
    mem_mb: float = 0.0
    mem_limit_mb: float = 0.0
    internet: bool = False


class LabError(RuntimeError):
    pass


class LabManager:
    """Fachada thread-safe sobre o Docker SDK para todo o lab."""

    def __init__(self) -> None:
        self._client: docker.DockerClient | None = None
        self._prev_stats: dict[str, tuple[float, int, int]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ base
    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def ensure_network(self) -> None:
        """Cria a rede interna isolada do lab, se ainda não existir."""
        try:
            self.client.networks.get(NETWORK_NAME)
            return
        except NotFound:
            pass
        ipam = docker.types.IPAMConfig(
            pool_configs=[docker.types.IPAMPool(subnet=SUBNET, gateway=GATEWAY)]
        )
        self.client.networks.create(
            NETWORK_NAME,
            driver="bridge",
            internal=True,            # sem rota para a internet
            ipam=ipam,
            labels={LABEL: "1"},
        )

    # ---------------------------------------------------------------- imagens
    def image_specs(self) -> dict[str, dict]:
        specs: dict[str, dict] = {"attacker": ATTACKER_SPEC}
        specs.update(self.all_targets())
        return specs

    def missing_images(self) -> list[str]:
        missing = []
        for name, spec in self.image_specs().items():
            try:
                self.client.images.get(spec["image"])
            except ImageNotFound:
                missing.append(name)
        return missing

    def build_images(
        self,
        only: list[str] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        """Constrói as imagens locais. ``progress`` recebe linhas de log."""
        log = progress or (lambda _line: None)
        specs = self.image_specs()
        for name in only or list(specs):
            spec = specs[name]
            log(f"[build] construindo {spec['image']} ...")
            _, logs = self.client.images.build(
                path=str(spec["context"]),
                dockerfile=spec["dockerfile"],
                tag=spec["image"],
                rm=True,
                labels={LABEL: "1"},
            )
            for chunk in logs:
                line = chunk.get("stream") or chunk.get("status") or ""
                if "error" in chunk:
                    raise LabError(f"erro no build de {spec['image']}: {chunk['error']}")
                line = line.strip()
                if line:
                    log(f"[build:{name}] {line}")
            log(f"[build] {spec['image']} pronta")

    # -------------------------------------------------------------- máquinas
    def _lab_containers(self) -> list:
        return self.client.containers.list(
            all=True, filters={"label": f"{LABEL}=1"}
        )

    def machines(self) -> list[Machine]:
        """Lista as máquinas do lab (sem métricas)."""
        result: list[Machine] = []
        for c in self._lab_containers():
            nets = c.attrs["NetworkSettings"]["Networks"]
            ip = nets.get(NETWORK_NAME, {}).get("IPAddress", "") or "-"
            result.append(
                Machine(
                    name=c.name,
                    kind=c.labels.get(f"{LABEL}.kind", "?"),
                    status=c.status,
                    ip=ip,
                    internet="bridge" in nets,
                )
            )
        result.sort(key=lambda m: (m.kind != "attacker", m.name))
        return result

    def ensure_attacker(self) -> None:
        """Garante que o container atacante existe e está rodando."""
        try:
            c = self.client.containers.get(ATTACKER_NAME)
            if c.status != "running":
                c.start()
            return
        except NotFound:
            pass
        TOOLS_DIR.mkdir(exist_ok=True)
        self.client.containers.create(
            ATTACKER_IMAGE,
            name=ATTACKER_NAME,
            hostname="attacker",
            network=NETWORK_NAME,
            volumes={str(TOOLS_DIR): {"bind": "/root/tools", "mode": "rw"}},
            cap_add=["NET_RAW", "NET_ADMIN"],
            stdin_open=True,
            tty=True,
            labels={LABEL: "1", f"{LABEL}.kind": "attacker"},
        ).start()

    def spawn_target(self, kind: str) -> str:
        """Cria e inicia um novo alvo do tipo informado. Retorna o nome."""
        specs = self.all_targets()
        if kind not in specs:
            raise LabError(f"tipo de alvo desconhecido: {kind}")
        existing = {m.name for m in self.machines() if m.kind == kind}
        idx = 1
        while f"cyberlab-{kind}-{idx}" in existing:
            idx += 1
        name = f"cyberlab-{kind}-{idx}"
        spec = specs[kind]
        self.client.containers.create(
            spec["image"],
            name=name,
            hostname=f"{kind}-{idx}",
            network=NETWORK_NAME,
            mem_limit=spec.get("mem_limit", "128m"),
            stdin_open=True,
            tty=True,
            labels={LABEL: "1", f"{LABEL}.kind": kind},
        ).start()
        return name

    def start(self, name: str) -> None:
        self.client.containers.get(name).start()

    def stop(self, name: str) -> None:
        self.client.containers.get(name).stop(timeout=3)

    def destroy(self, name: str) -> None:
        self.client.containers.get(name).remove(force=True)
        self._prev_stats.pop(name, None)

    def exec(self, name: str, cmd: list[str]) -> str:
        """Executa comando não-interativo e retorna a saída (para testes)."""
        code, out = self.client.containers.get(name).exec_run(cmd)
        return out.decode("utf-8", "replace").strip(), code

    # ------------------------------------------------ alvos/ferramentas custom
    def _load_registry(self) -> dict:
        try:
            data = json.loads(REGISTRY_PATH.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_registry(self, reg: dict) -> None:
        REGISTRY_PATH.write_text(json.dumps(reg, indent=2, ensure_ascii=False))

    @staticmethod
    def _slug(name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-")
        return slug or "app"

    def all_targets(self) -> dict[str, dict]:
        """Alvos built-in + custom (registry.json). Built-in têm precedência."""
        reg = self._load_registry()
        merged = dict(TARGETS)
        for name, spec in reg.get("targets", {}).items():
            if name not in merged and isinstance(spec, dict):
                merged[name] = spec
        return merged

    def add_target(self, path: str | Path, name: str | None = None) -> str:
        """'Compila' uma pasta com Dockerfile em imagem e registra como alvo."""
        context = Path(path).expanduser().resolve()
        if not (context / "Dockerfile").is_file():
            raise LabError(f"nenhum Dockerfile em {context}")
        name = self._slug(name or context.name)
        if name in TARGETS:
            raise LabError(f"'{name}' conflita com um alvo built-in")
        image = f"cyberlab/custom-{name}:latest"
        self.client.images.build(
            path=str(context), dockerfile="Dockerfile",
            tag=image, rm=True, labels={LABEL: "1"},
        )
        reg = self._load_registry()
        reg.setdefault("targets", {})[name] = {
            "image": image,
            "desc": f"alvo custom '{name}' ({context.name})",
            "services": "custom",
            "mem_limit": "128m",
            "context": str(context),
            "dockerfile": "Dockerfile",
        }
        self._save_registry(reg)
        return name

    def remove_target(self, name: str) -> None:
        reg = self._load_registry()
        spec = reg.get("targets", {}).pop(name, None)
        self._save_registry(reg)
        if spec:
            try:
                self.client.images.remove(spec["image"], force=True)
            except (APIError, ImageNotFound):
                pass

    def add_tool(self, path: str | Path, name: str | None = None) -> str:
        """Sincroniza uma pasta de ferramenta para /root/tools do atacante."""
        src = Path(path).expanduser().resolve()
        if not src.is_dir():
            raise LabError(f"{src} não é uma pasta")
        name = self._slug(name or src.name)
        TOOLS_DIR.mkdir(exist_ok=True)
        dest = TOOLS_DIR / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        reg = self._load_registry()
        reg.setdefault("tools", {})[name] = {"path": str(src), "synced": str(dest)}
        self._save_registry(reg)
        return name

    def list_tools(self) -> list[str]:
        reg = self._load_registry()
        return sorted(reg.get("tools", {}).keys())

    def remove_tool(self, name: str) -> None:
        reg = self._load_registry()
        info = reg.get("tools", {}).pop(name, None)
        self._save_registry(reg)
        if info and info.get("synced"):
            dest = Path(info["synced"])
            if dest.exists():
                shutil.rmtree(dest)

    def tool_entrypoint(self, name: str) -> str:
        """Detecta um entrypoint padrão na ferramenta montada no atacante."""
        base = f"/root/tools/{name}"
        candidates = ["main.py", "app.py", "run.py", "tool.py", "main.sh", "run.sh"]
        for c in candidates:
            if (TOOLS_DIR / name / c).is_file():
                if c.endswith(".py"):
                    return f"python3 {c}"
                return f"sh {c}"
        if (TOOLS_DIR / name / "main").is_file():
            return "./main"
        return "sh"  # fallback: abre um shell dentro da pasta

    def run_tool(
        self, name: str, args: list[str], entrypoint: str | None = None
    ) -> int:
        """Executa uma ferramenta dentro do atacante (rede do lab). Retorna o código."""
        entry = entrypoint or self.tool_entrypoint(name)
        cmdline = [*shlex.split(entry), *[str(a) for a in args]]
        command = (
            f"cd /root/tools/{name} && " + " ".join(shlex.quote(a) for a in cmdline)
        )
        flags = "-it" if sys.stdin.isatty() else "-i"
        return subprocess.call(
            ["docker", "exec", flags, ATTACKER_NAME, "sh", "-c", command]
        )

    # --------------------------------------------------------- internet NAT
    def set_internet(self, enabled: bool) -> bool:
        """Conecta/desconecta o atacante da rede bridge (NAT -> internet)."""
        bridge = self.client.networks.get("bridge")
        current = self.internet_enabled()
        try:
            if enabled and not current:
                bridge.connect(ATTACKER_NAME)
            elif not enabled and current:
                bridge.disconnect(ATTACKER_NAME, force=True)
        except (NotFound, APIError):
            pass
        return self.internet_enabled()

    def internet_enabled(self) -> bool:
        try:
            c = self.client.containers.get(ATTACKER_NAME)
        except NotFound:
            return False
        return "bridge" in c.attrs["NetworkSettings"]["Networks"]

    # ---------------------------------------------------------------- stats
    def sample_stats(self) -> dict[str, tuple[float, float, float]]:
        """
        Coleta CPU%/RAM de cada container em execução.

        Retorna ``{nome: (cpu_percent, mem_mb, mem_limit_mb)}``.
        CPU% é calculada por delta entre amostras (padrão `docker stats`).
        """
        out: dict[str, tuple[float, float, float]] = {}
        alive: set[str] = set()
        now = time.monotonic()
        for c in self._lab_containers():
            if c.status != "running":
                continue
            try:
                s = c.stats(stream=False)
            except (NotFound, APIError):
                continue
            alive.add(c.name)
            cpu_total = s["cpu_stats"]["cpu_usage"].get("total_usage", 0)
            sys_total = s["cpu_stats"].get("system_cpu_usage", 0)
            ncpu = s["cpu_stats"].get("online_cpus") or len(
                s["cpu_stats"]["cpu_usage"].get("percpu_usage") or [1]
            )
            cpu_pct = 0.0
            prev = self._prev_stats.get(c.name)
            if prev is not None:
                _, prev_cpu, prev_sys = prev
                d_cpu = cpu_total - prev_cpu
                d_sys = sys_total - prev_sys
                if d_cpu > 0 and d_sys > 0:
                    cpu_pct = (d_cpu / d_sys) * ncpu * 100.0
            self._prev_stats[c.name] = (now, cpu_total, sys_total)

            mem = s.get("memory_stats", {})
            usage = mem.get("usage", 0)
            # em cgroups v2 desconta cache de páginas inativas (como o CLI)
            usage -= mem.get("stats", {}).get("inactive_file", 0)
            limit = mem.get("limit", 0)
            out[c.name] = (round(cpu_pct, 1), usage / 1e6, limit / 1e6)
        for stale in set(self._prev_stats) - alive:
            del self._prev_stats[stale]
        return out

    def host_stats(self) -> dict[str, float]:
        """Uso geral do hardware do host (para comparar com o consumo do lab)."""
        mem = psutil.virtual_memory()
        return {
            "cpu": psutil.cpu_percent(interval=None),
            "mem_used_gb": (mem.total - mem.available) / 1e9,
            "mem_total_gb": mem.total / 1e9,
            "mem_pct": mem.percent,
        }

    # -------------------------------------------------------------- teardown
    def nuke(self, progress: Callable[[str], None] | None = None) -> None:
        """Remove TODOS os containers e a rede do lab."""
        log = progress or (lambda _line: None)
        for c in self._lab_containers():
            log(f"[nuke] removendo {c.name}")
            try:
                c.remove(force=True)
            except APIError as exc:
                log(f"[nuke] falha em {c.name}: {exc}")
        try:
            self.client.networks.get(NETWORK_NAME).remove()
            log(f"[nuke] rede {NETWORK_NAME} removida")
        except NotFound:
            pass
        self._prev_stats.clear()
