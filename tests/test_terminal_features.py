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

    print(f"\n{sum(CHECKS)}/{len(CHECKS)} verificações passaram")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())