#!/usr/bin/env python3
"""
Testa as capacidades do terminal embutido de forma unitária (sem TUI):

  - cores 16/256/24-bit (truecolor), bold, reverse
  - alternate screen (nano/vim/less) com preservação do buffer principal
  - application cursor mode (DECCKM) para as setas do nano

    python tests/test_terminal_features.py
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyte  # noqa: E402
from lab.terminal import Terminal, _cell_style, _color  # noqa: E402

CHECKS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    # ---- cores
    check("cor nomeada (16)", _color("red", None) == "#800000")
    check("cor 256/truecolor hex", _color("ff0000", None) == "#ff0000")
    check("cor 'default' usa fallback", _color("default", "X") == "X")
    check("valor None usa fallback", _color(None, "X") == "X")
    check("rgb já pronto é preservado", _color("#abc", None) == "#abc")

    char = pyte.screens.Char(
        "X", "ff0000", "0000ff", bold=True, italics=False,
        underscore=True, strikethrough=False, reverse=False,
    )
    st = _cell_style(char)
    s = str(st)
    check("truecolor fg", "#ff0000" in s)
    check("truecolor bg", "#0000ff" in s, s)
    check("bold", "bold" in s)
    check("underline", "underline" in s)

    # ---- alternate screen
    term = Terminal(["sh"])
    term._buflock = threading.Lock()
    term._feed(b"linha_principal\n")
    check("buffer principal escrito", "linha_principal" in term._main_screen.display[0])

    term._feed(b"\x1b[?1049h")
    check("1049h troca p/ alternate", term._screen is term._alt_screen)
    term._feed(b"linha_alt\n")
    check("conteúdo vai para o alt", "linha_alt" in term._alt_screen.display[0])
    check("principal preservado", "linha_principal" in term._main_screen.display[0])

    term._feed(b"\x1b[?1049l")
    check("1049l retorna ao principal", term._screen is term._main_screen)
    check("principal intacto após voltar", "linha_principal" in term._main_screen.display[0])

    # ---- application cursor mode (DECCKM)
    term._feed(b"\x1b[?1h")
    check("?1h ativa application mode", term._app_cursor is True)
    term._feed(b"\x1b[?1l")
    check("?1l desativa application mode", term._app_cursor is False)

    # ---- split da sequência de controle entre chunks
    term._feed(b"\x1b[?10")
    term._feed(b"49h")
    check("sequência split entre chunks detectada", term._screen is term._alt_screen)
    term._feed(b"\x1b[?1049l")

    # ---- seleção de texto (copiar)
    t2 = Terminal(["sh"])
    t2._buflock = threading.Lock()
    t2._feed(b"linha_um\nlinha_dois\n")
    lines = t2._visible_lines()
    check("linha reconstruída do buffer",
          t2._line_text(lines[0], t2._screen.columns).startswith("linha_um"))
    t2._sel_start = (0, 6)
    t2._sel_end = (0, 8)
    check("seleção extrai o texto", t2._selected_text() == "um", repr(t2._selected_text()))

    # ---- FIX-9: terminal morto consome teclas (não dispara ações globais da TUI)
    from textual import events as _events

    t3 = Terminal(["sh"])
    t3._buflock = threading.Lock()
    t3._dead = True
    for key in ("x", "s", "i", "a", "u"):
        evt = _events.Key(key=key, character=key)
        t3.on_key(evt)
        if not evt._stop_propagation:
            check(f"terminal morto consome tecla {key!r}", False)
            break
    else:
        check("terminal morto consome teclas (x/s/i/a/u não vazam p/ a TUI)", True)

    # ---- FIX-10: resize das telas pyte acontece sob _buflock
    t4 = Terminal(["sh"])
    t4._buflock = threading.Lock()
    errors: list = []

    def _hammer_feed() -> None:
        try:
            for _ in range(400):
                # espelha o _reader real: o feed SEMPRE acontece sob _buflock
                with t4._buflock:
                    t4._feed(b"linha de saida\r\n")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    feeder = threading.Thread(target=_hammer_feed)
    feeder.start()
    try:
        for _ in range(40):
            t4._resize_terminal(90, 30)
            t4._resize_terminal(80, 24)
    finally:
        feeder.join()
    check("resize concorrente com feed não corrompe pyte", not errors, repr(errors))
    check("dimensões aplicadas", (t4._cols, t4._rows) == (80, 24))

    # ---- FIX-9b: bindings priority (ctrl+q) continuam vivos com painel morto
    # (o widget morto consome teclas comuns, mas não pode prender o usuário)
    if sys.platform != "win32":
        import asyncio

        from textual.app import App, ComposeResult
        from textual.binding import Binding

        leaked: list = []

        class _DeadKeyApp(App):
            BINDINGS = [
                Binding("ctrl+q", "quit", "sair", priority=True),
                Binding("x", "boom", "x"),
            ]

            def compose(self) -> ComposeResult:
                yield Terminal(["sh"])

            def action_boom(self) -> None:
                leaked.append("boom")

        async def _dead_keys() -> bool:
            app = _DeadKeyApp()
            async with app.run_test(size=(80, 24)) as pilot:
                term = app.query_one(Terminal)
                term.focus()
                await pilot.pause(0.4)
                term._dead = True
                await pilot.press("x")
                await pilot.pause(0.2)
                await pilot.press("ctrl+q")
                await pilot.pause(0.5)
            return not leaked

        ok = asyncio.run(_dead_keys())
        check("tecla comum não vaza p/ bindings; ctrl+q (priority) ainda sai", ok, repr(leaked))

    print(f"\n{sum(CHECKS)}/{len(CHECKS)} verificações passaram")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())