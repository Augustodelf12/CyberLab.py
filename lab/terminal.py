"""
Widget de terminal real para a TUI: PTY local (pyte/ptyprocess) renderizado
como Rich Text. Usado para rodar `docker exec -it <máquina> <shell>` dentro
das abas do dashboard.
"""
from __future__ import annotations

import os
import sys
import threading

import pyte
from ptyprocess import PtyProcess
from rich.style import Style
from rich.text import Text
from textual import events
from textual.widget import Widget

# --------------------------------------------------------------------------
# cores: pyte entrega nomes ANSI ou hex do índice 0-255; convertemos p/ Rich
# --------------------------------------------------------------------------
_NAMED = {
    "black": "#000000", "red": "#800000", "green": "#008000", "brown": "#808000",
    "blue": "#000080", "magenta": "#800080", "cyan": "#008080", "white": "#c0c0c0",
    "brightblack": "#808080", "brightred": "#ff0000", "brightgreen": "#00ff00",
    "brightbrown": "#ffff00", "brightblue": "#5c5cff", "brightmagenta": "#ff00ff",
    "brightcyan": "#00ffff", "brightwhite": "#ffffff",
}
_BASE16 = [
    "#000000", "#800000", "#008000", "#808000", "#000080", "#800080", "#008080",
    "#c0c0c0", "#808080", "#ff0000", "#00ff00", "#ffff00", "#0000ff", "#ff00ff",
    "#00ffff", "#ffffff",
]


def _xterm256(n: int) -> str:
    if n < 16:
        return _BASE16[n]
    if n < 232:
        n -= 16
        r, rest = divmod(n, 36)
        g, b = divmod(rest, 6)
        conv = lambda v: 0 if v == 0 else 55 + 40 * v
        return f"#{conv(r):02x}{conv(g):02x}{conv(b):02x}"
    level = 8 + 10 * (n - 232)
    return f"#{level:02x}{level:02x}{level:02x}"


def _color(value: str | None, fallback: str | None) -> str | None:
    if not value or value == "default":
        return fallback
    if value in _NAMED:
        return _NAMED[value]
    try:
        return _xterm256(int(value, 16))
    except ValueError:
        return value  # já é rich-compatible (#rrggbb / nome)


def _cell_style(char: pyte.screens.Char) -> Style:
    fg = _color(char.fg, None)
    bg = _color(char.bg, None)
    style = Style(color=fg, bgcolor=bg)
    if char.bold:
        style += Style(bold=True)
    if char.underscore:
        style += Style(underline=True)
    if char.italics:
        style += Style(italic=True)
    if char.reverse:
        style += Style(reverse=True)
    return style


_KEYMAP = {
    "enter": b"\r",
    "backspace": b"\x7f",
    "tab": b"\t",
    "shift+tab": b"\x1b[Z",
    "escape": b"\x1b",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "delete": b"\x1b[3~",
    "insert": b"\x1b[2~",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "f1": b"\x1bOP", "f2": b"\x1bOQ", "f3": b"\x1bOR", "f4": b"\x1bOS",
    "f5": b"\x1b[15~", "f6": b"\x1b[17~", "f7": b"\x1b[18~", "f8": b"\x1b[19~",
    "f9": b"\x1b[20~", "f10": b"\x1b[21~", "f11": b"\x1b[23~", "f12": b"\x1b[24~",
}


class Terminal(Widget):
    """Um terminal interativo (xterm minimamente viável) embutido na TUI."""

    can_focus = True

    DEFAULT_CSS = """
    Terminal {
        background: #0c0c0c;
        border: round #2c4a2c;
        border-title-color: #6f6;
        padding: 0 1;
    }
    Terminal:focus {
        border: round #00ff41;
    }
    """

    def __init__(self, argv: list[str], *, title: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._argv = argv
        if title:
            self.border_title = title
        cols, rows = 80, 24
        # HistoryScreen mantém as linhas que saem da tela em history.top
        self._screen = pyte.HistoryScreen(columns=cols, lines=rows, history=2000)
        self._stream = pyte.ByteStream(self._screen)
        self._buflock = threading.Lock()  # pyte não é thread-safe
        self._proc: PtyProcess | None = None
        self._dead = False
        self._refresh_pending = False
        self._read_thread: threading.Thread | None = None
        self._scroll = 0  # linhas de scrollback acima do fundo (0 = seguir o fim)

    # ------------------------------------------------------------- ciclo de vida
    def on_mount(self) -> None:
        try:
            self._proc = PtyProcess.spawn(self._argv, dimensions=(24, 80))
        except Exception as exc:  # ex.: docker ausente ou Windows sem pty
            hint = ""
            if sys.platform == "win32":
                hint = "\r\n[dica: no Windows, rode a TUI via WSL2 p/ terminais embutidos]\r\n"
            self._stream.feed(
                f"\r\n[falha ao iniciar terminal: {exc}]{hint}\r\n".encode()
            )
            self._dead = True
            return
        self._read_thread = threading.Thread(target=self._reader, daemon=True)
        self._read_thread.start()

    def on_unmount(self) -> None:
        self._dead = True
        if self._proc and self._proc.isalive():
            try:
                self._proc.terminate(force=True)
            except Exception:
                pass

    # ------------------------------------------------------------------- leitura
    def _reader(self) -> None:
        fd = self._proc.fd
        while not self._dead:
            try:
                chunk = os.read(fd, 65536)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            with self._buflock:
                self._stream.feed(chunk)
            try:
                self.app.call_from_thread(self._pump_refresh)
            except Exception:
                break  # app já encerrou
        self._dead = True
        try:
            self.app.call_from_thread(self._on_process_exit)
        except Exception:
            pass

    def _pump_refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self.set_timer(1 / 30, self._do_refresh)

    def _do_refresh(self) -> None:
        self._refresh_pending = False
        self.refresh()

    def _on_process_exit(self) -> None:
        if self._proc and self._proc.exitstatus is not None:
            status = self._proc.exitstatus
        else:
            status = "?"
        with self._buflock:
            self._stream.feed(
                f"\r\n\x1b[90m[processo encerrado — código {status}]\x1b[0m\r\n".encode()
            )
        self._dead = True
        self._update_subtitle()
        self.refresh()

    # -------------------------------------------------------------------- input
    def on_key(self, event: events.Key) -> None:
        if self._dead or not self._proc:
            return
        key = event.key

        # rolagem do scrollback (não vai para o processo)
        page = max(1, self._screen.lines - 2)
        if key == "shift+up":
            self._shift_scroll(1)
            event.stop()
            return
        if key == "shift+down":
            self._shift_scroll(-1)
            event.stop()
            return
        if key == "shift+pageup":
            self._shift_scroll(page)
            event.stop()
            return
        if key == "shift+pagedown":
            self._shift_scroll(-page)
            event.stop()
            return

        data: bytes | None = None
        char = event.character
        if char and char.isprintable():
            data = char.encode("utf-8")
        elif key in _KEYMAP:
            data = _KEYMAP[key]
        elif key.startswith("ctrl+"):
            rest = key[5:]
            if len(rest) == 1 and rest.isalpha():
                data = bytes([ord(rest.lower()) - 96])
            elif rest == "space":
                data = b"\x00"
        if data is not None:
            if self._scroll > 0:  # digitar volta à posição de seguir o fim
                self._shift_scroll(-self._scroll)
            try:
                self._proc.write(data)
            except (OSError, ValueError):
                self._dead = True
            event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self._shift_scroll(3)
        event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self._shift_scroll(-3)
        event.stop()

    def _shift_scroll(self, delta: int) -> None:
        old = self._scroll
        self._scroll = max(0, old + delta)
        if self._scroll != old:
            self._update_subtitle()
            self.refresh()

    def _update_subtitle(self) -> None:
        if self._scroll > 0:
            self.border_subtitle = f"rolado -{self._scroll} linha(s)"
        elif self._dead:
            self.border_subtitle = "encerrado"
        else:
            self.border_subtitle = ""

    # ------------------------------------------------------------------ resize
    def on_resize(self, event: events.Resize) -> None:
        w = max(event.size.width - 2, 10)   # desconta borda
        h = max(event.size.height - 2, 3)
        self._screen.resize(lines=h, columns=w)
        if self._proc and self._proc.isalive():
            try:
                self._proc.setwinsize(h, w)
            except Exception:
                pass
        self.refresh()

    # ------------------------------------------------------------------ render
    def render(self) -> Text:
        screen = self._screen
        show_cursor = (
            self.has_focus
            and not screen.cursor.hidden
            and not self._dead
            and self._scroll <= 0
        )
        cx, cy = screen.cursor.x, screen.cursor.y
        with self._buflock:
            if self._scroll > 0:
                history = list(screen.history.top)
            else:
                history = []
            buffer_lines = [screen.buffer.get(y, {}) for y in range(screen.lines)]
            columns = screen.columns
        # projeta a janela visível: linhas do histórico (scrollback) + viewport
        max_scroll = len(history)
        if self._scroll > max_scroll:
            self._scroll = max_scroll
        if self._scroll <= 0:
            lines = [(y, buffer_lines[y]) for y in range(screen.lines)]
        else:
            top_src = max_scroll - self._scroll
            lines = []
            for i in range(screen.lines):
                src = top_src + i
                if src < max_scroll:
                    lines.append((i, history[src]))
                else:
                    lines.append((i, buffer_lines[src - max_scroll]))

        text = Text()
        for y, line in lines:
            run_style: Style | None = None
            run_chars: list[str] = []
            for x in range(columns):
                char = line.get(x, _BLANK)
                style = _cell_style(char)
                if show_cursor and y == cy and x == cx:
                    style = style + Style(reverse=True)
                if style != run_style and run_chars:
                    text.append("".join(run_chars), style=run_style)
                    run_chars = []
                run_style = style
                run_chars.append(char.data)
            if run_chars:
                text.append("".join(run_chars), style=run_style)
            if y < screen.lines - 1:
                text.append("\n")
        return text


_BLANK = pyte.screens.Char(" ", "default", "default", False, False, False, False, False)
