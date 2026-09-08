#!/usr/bin/env python3
"""
Testa o fluxo de alvos/ferramentas customizados (registry + CLI/TUI backend):

  - 'compilar' uma pasta com Dockerfile como alvo, spawná-lo, destruí-lo e removê-lo
  - sincronizar uma pasta de ferramenta para o atacante e removê-la

    python tests/test_custom.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab.manager import LabManager  # noqa: E402


def main() -> int:
    m = LabManager()
    m.ensure_network()
    m.ensure_attacker()

    base = Path(tempfile.mkdtemp(prefix="cyberlab-test-"))
    results = []

    def check(name, ok, extra=""):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {extra}")

    try:
        # ---- alvo custom
        tgt_dir = base / "evil-app"
        tgt_dir.mkdir()
        (tgt_dir / "Dockerfile").write_text(
            'FROM alpine:3.20\nCMD ["sh", "-c", "echo estou_vivo && sleep infinity"]\n'
        )
        name = m.add_target(tgt_dir, "tmptgt")
        check("add_target registra alvo custom", "tmptgt" in m.all_targets(), name)

        created = m.spawn_target("tmptgt")
        kinds = {mm.kind for mm in m.machines()}
        check("spawn_target roda o alvo custom", "tmptgt" in kinds, created)

        out, code = m.exec(created, ["sh", "-c", "echo marcar_job"])
        check("container custom executável", "marcar_job" in out, repr(out))

        m.destroy(created)
        m.remove_target("tmptgt")
        check("remove_target limpa registry", "tmptgt" not in m.all_targets())

        # ---- ferramenta custom
        tool_dir = base / "scan-tool"
        tool_dir.mkdir()
        (tool_dir / "main.py").write_text('print("tool_importada_ok")\n')
        name = m.add_tool(tool_dir, "tmptool")
        check("add_tool registra ferramenta", name == "tmptool" and "tmptool" in m.list_tools())

        out, code = m.exec(
            "cyberlab-attacker", ["cat", "/root/tools/tmptool/main.py"]
        )
        check("ferramenta visível no atacante", "tool_importada_ok" in out, repr(out))
        entry = m.tool_entrypoint("tmptool")
        check("entrypoint detectado", entry == "python3 main.py", entry)

        m.remove_tool("tmptool")
        check("remove_tool limpa registry", "tmptool" not in m.list_tools())
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print(f"\n{sum(results)}/{len(results)} verificações passaram")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())