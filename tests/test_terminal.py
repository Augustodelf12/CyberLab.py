#!/usr/bin/env python3
"""
Testa o widget Terminal: digita comandos na aba do atacante e confere a saída
renderizada no buffer (PTY + pyte funcionando de verdade) e o scrollback.

    python tests/test_terminal.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab.app import CyberLabApp  # noqa: E402
from lab.terminal import Terminal  # noqa: E402


async def main() -> int:
    ok_all = True
    app = CyberLabApp()
    async with app.run_test(size=(120, 42)) as pilot:
        await pilot.pause(6)

        term = next(iter(app.query(Terminal)), None)
        assert term is not None, "nenhum terminal aberto"
        term.focus()
        await pilot.pause(0.5)

        # 1) comando simples: echo
        for ch in "echo LAB_$((6*7))":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(2)
        content = term.render().plain
        ok1 = "LAB_42" in content
        ok_all &= ok1
        print(f"[{'PASS' if ok1 else 'FAIL'}] terminal executa comando e renderiza")

        # 2) scrollback: gera linhas numeradas únicas e rola até o início
        for ch in "seq 100 200":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(2)
        bottom = term.render().plain
        ok2a = "200" in bottom
        ok_all &= ok2a
        print(f"[{'PASS' if ok2a else 'FAIL'}] saída longa renderizada no fundo")

        term._shift_scroll(10000)  # rola até o topo do scrollback
        await pilot.pause(0.2)
        top = term.render().plain.lstrip("\n")
        ok2b = "101" in top          # '101' só existe nas primeiras linhas (já fora da tela)
        ok_all &= ok2b
        print(f"[{'PASS' if ok2b else 'FAIL'}] scrollback recupera linhas antigas "
              f"(topo mostra '101': {repr(top[:30])})")

        # 3) voltar ao fundo
        term._shift_scroll(-10000)
        await pilot.pause(0.2)
        back = term.render().plain
        ok3 = "200" in back and term._scroll == 0
        ok_all &= ok3
        print(f"[{'PASS' if ok3 else 'FAIL'}] volta ao fundo (scroll resetado)")

    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))