"""
Widget de terminal real para a TUI: PTY local (pyte/ptyprocess) renderizado
como Rich Text. Usado para rodar `docker exec -it <máquina> <shell>` dentro
das abas do dashboard.

Suporta: cores de 16/256/24 bits, bold/itálico/sublinhado/reverso, scrollback,
alternate screen (nano/vim/less) e application cursor mode (setas do nano).
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
# cores: pyte entrega nomes ANSI ("red") ou hex de 6 dígitos ("ff0000")
# --------------------------------------------------------------------------
_NAMED = {
    "black": "#000000", "red": "#800000", "green": "#008000", "brown": "#808000",
    "blue": "#000080", "magenta": "#800080", "cyan": "#008080", "white": "#c0c0c0",
    "brightblack": "#808080", "brightred": "#ff0000", "brightgreen": "#00ff00",
    "brightbrown": "#ffff00", "brightblue": "#5c5cff", "brightmagenta": "#ff00ff",
    "brightcyan": "#00ffff", "brightwhite": "#ffffff",
}


def _color(value: str | None, fallback: str | None) -> str | None:
    if not value or value == "default":
        return fallback
    if value in _NAMED:
        return _NAMED[value]
    # 256 e truecolor (24-bit) chegam como hex de 6 dígitos (ex.: "ff0000")
    if len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
        return "#" + value
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
    "delete": b"\x1b[3~",
    "insert": b"\x1b[2~",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "f1": b"\x1bOP", "f2": b"\x1bOQ", "f3": b"\x1bOR", "f4": b"\x1bOS",
    "f5": b"\x1b[15~", "f6": b"\x1b[17~", "f7": b"\x1b[18~", "f8": b"\x1b[19~",
    "f9": b"\x1b[20~", "f10": b"\x1b[21~", "f11": b"\x1b[23~", "f12": b"\x1b[24~",
}

# Sequências de controle que interceptamos (alternate screen + modo de cursor)
_CTRL_SEQS: dict[bytes, str] = {
    b"\x1b[?1049h": "alt_enter",
    b"\x1b[?1047h": "alt_enter",
    b"\x1b[?1049l": "alt_leave",
    b"\x1b[?1047l": "alt_leave",
    b"\x1b[?1h": "cursor_app_on",
    b"\x1b[?1l": "cursor_app_off",
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
        self._cols, self._rows = cols, rows
        # tela principal (com scrollback) + tela alternativa (nano/vim/less)
        self._main_screen = pyte.HistoryScreen(columns=cols, lines=rows, history=2000)
        self._alt_screen = pyte.HistoryScreen(columns=cols, lines=rows, history=2000)
        self._screen = self._main_screen
        self._stream = pyte.ByteStream(self._screen)
        self._buflock = threading.Lock()  # pyte não é thread-safe
        self._proc: PtyProcess | None = None
        self._dead = False
        self._refresh_pending = False
        self._read_thread: threading.Thread | None = None
        self._scroll = 0          # linhas de scrollback acima do fundo (0 = fim)
        self._app_cursor = False  # DECCKM: setas em application mode (nano)
        self._pending = b""       # bytes aguardando sequência de controle split

    # ------------------------------------------------------------- ciclo de vida
    def on_mount(self) -> None:
        try:
            self._proc = PtyProcess.spawn(self._argv, dimensions=(24, 80))
        except Exception as exc:  # ex.: docker ausente ou Windows sem pty
            hint = ""
            if sys.platform == "win32":
                hint = "\r\n[dica: no Windows, rode a TUI via WSL2 p/ terminais embutidos]\r\n"
            with self._buflock:
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
                self._feed(chunk)
            try:
                self.app.call_from_thread(self._pump_refresh)
            except Exception:
                break  # app já encerrou
        self._dead = True
        with self._buflock:
            if self._pending:
                self._stream.feed(self._pending)
                self._pending = b""
        try:
            self.app.call_from_thread(self._on_process_exit)
        except Exception:
            pass

    def _feed(self, data: bytes) -> None:
        """Roteia o fluxo, interceptando alternate-screen e modo de cursor."""
        buf = self._pending + data
        self._pending = b""
        while buf:
            # 1) há alguma sequência completa?
            best = None
            for seq, action in _CTRL_SEQS.items():
                idx = buf.find(seq)
                if idx != -1 and (best is None or idx < best[0]):
                    best = (idx, seq, action)
            if best is not None:
                idx, seq, action = best
                self._stream.feed(buf[:idx])
                self._apply_ctrl(action)
                buf = buf[idx + len(seq):]
                continue
            # 2) sem sequência completa: alimenta tudo, exceto um sufixo que
            #    começa em ESC e seja prefixo de alguma sequência (split entre
            #    chunks). Assim os dados fluem imediatamente.
            last_esc = buf.rfind(b"\x1b")
            if last_esc != -1:
                suffix = buf[last_esc:]
                is_prefix = any(
                    seq.startswith(suffix) and len(suffix) < len(seq)
                    for seq in _CTRL_SEQS
                )
                if is_prefix:
                    self._stream.feed(buf[:last_esc])
                    self._pending = suffix
                    return
            self._stream.feed(buf)
            return

    def _apply_ctrl(self, action: str) -> None:
        if action == "alt_enter":
            self._switch_screen(self._alt_screen)
        elif action == "alt_leave":
            self._switch_screen(self._main_screen)
        elif action == "cursor_app_on":
            self._app_cursor = True
        elif action == "cursor_app_off":
            self._app_cursor = False

    def _switch_screen(self, screen) -> None:
        if screen is self._screen:
            return
        self._screen = screen
        self._stream = pyte.ByteStream(screen)
        self._screen.resize(lines=self._rows, columns=self._cols)
        self._scroll = 0

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
            self._feed(
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

        # setas + home/end respeitam o application cursor mode (nano)
        if key in ("up", "down", "right", "left"):
            normal = {"up": b"\x1b[A", "down": b"\x1b[B", "right": b"\x1b[C", "left": b"\x1b[D"}
            application = {"up": b"\x1bOA", "down": b"\x1bOB", "right": b"\x1bOC", "left": b"\x1bOD"}
            self._write(application[key] if self._app_cursor else normal[key])
            event.stop()
            return
        if key == "home":
            self._write(b"\x1bOH" if self._app_cursor else b"\x1b[H")
            event.stop()
            return
        if key == "end":
            self._write(b"\x1bOF" if self._app_cursor else b"\x1b[F")
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
            self._write(data)
            event.stop()

    def _write(self, data: bytes) -> None:
        if self._scroll > 0:  # digitar volta à posição de seguir o fim
            self._shift_scroll(-self._scroll)
        try:
            self._proc.write(data)
        except (OSError, ValueError):
            self._dead = True

    def on_paste(self, event: events.Paste) -> None:
        """Cola o conteúdo do clipboard no terminal (Ctrl+Shift+V no host)."""
        if not self._dead and self._proc:
            self._write(event.text.encode("utf-8"))
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
        self._cols, self._rows = w, h
        self._main_screen.resize(lines=h, columns=w)
        self._alt_screen.resize(lines=h, columns=w)
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