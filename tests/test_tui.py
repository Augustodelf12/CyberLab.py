#!/usr/bin/env python3
"""
Teste headless da TUI (usa o modo run_test do Textual — sem terminal real).

Valida: montagem, setup, tabela de máquinas, sparklines, modal de novo alvo,
abertura de terminais em abas e ações de start/stop/destroy.

    python tests/test_tui.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab.app import CyberLabApp, ImportModal, TargetModal  # noqa: E402
from lab.manager import LabManager  # noqa: E402
from textual.widgets import DataTable, ListView, RichLog, Sparkline  # noqa: E402

CHECKS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def wait_status(mgr, pilot, name: str, want: str, timeout: float = 20.0) -> str:
    """Aguarda o container chegar ao estado desejado (stop leva alguns segundos)."""
    cur = "?"
    for _ in range(int(timeout * 2)):
        cur = {m.name: m.status for m in mgr.machines()}.get(name, "gone")
        if cur == want:
            return cur
        await pilot.pause(0.5)
    return cur


async def main() -> int:
    # alvo fresco para o modal criar
    mgr = LabManager()
    for mch in mgr.machines():
        if mch.kind == "webvuln":
            mgr.destroy(mch.name)

    app = CyberLabApp()
    async with app.run_test(size=(150, 50)) as pilot:
        await pilot.pause(6)  # setup: rede + attacker + primeira coleta de stats

        table = app.query_one("#machines", DataTable)
        check("tabela lista o atacante", table.row_count >= 1)

        log = app.query_one("#events", RichLog)
        check("log de eventos registrou o setup", len(log.lines) >= 2)

        check("aba do terminal do atacante aberta", "pane-cyberlab-attacker" in app._open_panes)

        cpu_spark = app.query_one("#spark-cpu", Sparkline)
        check("sparkline de CPU recebendo dados", len(list(cpu_spark.data)) > 1)

        # modal de novo alvo via atalho
        await pilot.press("ctrl+n")
        await pilot.pause(0.8)
        check("ctrl+n abriu o modal de alvos", isinstance(app.screen, TargetModal))

        lv = app.screen.query_one(ListView)
        lv.focus()
        await pilot.pause(0.3)
        await pilot.press("enter")  # primeiro item = webvuln
        await pilot.pause(3)
        names = [m.name for m in mgr.machines()]
        check("alvo webvuln criado pelo modal", any("webvuln" in n for n in names), str(names))
        check(
            "terminal do novo alvo aberto em aba",
            any("webvuln" in p for p in app._open_panes),
        )

        web_name = next(n for n in names if "webvuln" in n)

        # seleciona a linha do alvo e testa stop/start via teclas
        # (o foco estava no terminal do alvo — volta para a tabela primeiro)
        for _ in range(30):  # espera o tick de stats enxergar o novo alvo
            if any(m.name == web_name for m in app._last_machines):
                break
            await pilot.pause(0.5)
        table.focus()
        await pilot.pause(1.5)  # um tick aplica _pending_select -> cursor no alvo
        check("linha do novo alvo selecionada automaticamente",
              app._selected_name() == web_name, app._selected_name())
        await pilot.press("s")  # stop
        status = await wait_status(mgr, pilot, web_name, "exited")
        check("tecla 's' parou o alvo", status == "exited", status)

        await pilot.pause(1.2)  # deixa a UI receber o novo estado antes do toggle
        await pilot.press("s")  # start
        status = await wait_status(mgr, pilot, web_name, "running")
        check("tecla 's' religou o alvo", status == "running", status)

        # destroy via 'x' + modal de confirmação
        await pilot.press("x")
        await pilot.pause(0.8)
        await pilot.press("y")
        await pilot.pause(3)
        names = [m.name for m in mgr.machines()]
        check("tecla 'x' + confirmação destruíram o alvo", web_name not in names)
        check("aba do alvo removida", f"pane-{web_name}" not in app._open_panes)

        # modal de importação (alvo/ferramenta)
        await pilot.press("a")
        await pilot.pause(0.8)
        check("tecla 'a' abriu o modal de importação", isinstance(app.screen, ImportModal))
        await pilot.press("escape")
        await pilot.pause(0.5)
        check("escape fecha o modal de importação", not isinstance(app.screen, ImportModal))

    print(f"\n{sum(CHECKS)}/{len(CHECKS)} verificações passaram")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
