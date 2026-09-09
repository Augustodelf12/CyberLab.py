"""
TUI do CyberLab (Textual).

Painéis:
  - esquerda: lista de máquinas + ações
  - em cima: medidores (host vs. consumo do lab, com sparklines)
  - embaixo: abas com terminais reais (atacante, alvos) e log de eventos
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Sparkline,
    Static,
    TabbedContent,
    TabPane,
)

from . import __version__
from .manager import ATTACKER_NAME, LabManager, Machine
from .cli import self_update
from .terminal import Terminal

_SHELLS = {"attacker": "/bin/bash"}


def _shell_for(kind: str) -> str:
    return _SHELLS.get(kind, "/bin/sh")


# ---------------------------------------------------------------------- modais
class TargetModal(ModalScreen[str | None]):
    """Escolha do tipo de alvo a ser criado."""

    BINDINGS = [Binding("escape", "cancel", "cancelar")]

    CSS = """
    TargetModal { align: center middle; }
    TargetModal #dialog {
        width: 72; height: auto; max-height: 80%;
        border: round #00ff41; background: $surface; padding: 1 2;
    }
    TargetModal ListView { height: auto; max-height: 14; }
    """

    def __init__(self, targets: dict) -> None:
        super().__init__()
        self._targets = targets

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Novo alvo[/] — escolha o tipo:")
            yield ListView(
                *(
                    ListItem(
                        Label(f"{kind:8s} {spec['services']:10s} {spec['desc']}"),
                        id=kind,
                    )
                    for kind, spec in self._targets.items()
                ),
                id="target-list",
            )
            yield Label("[dim]enter confirma · esc cancela[/]")

    @on(ListView.Selected, "#target-list")
    def _picked(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ImportModal(ModalScreen[tuple[str, str] | None]):
    """Importa uma pasta como alvo (Dockerfile) ou ferramenta. Retorna (tipo, caminho)."""

    BINDINGS = [Binding("escape", "cancel", "cancelar")]

    CSS = """
    ImportModal { align: center middle; }
    ImportModal #dialog {
        width: 76; height: auto; border: round #00ff41;
        background: $surface; padding: 1 2;
    }
    ImportModal Input { width: 100%; margin: 1 0; }
    ImportModal #row { height: auto; align-horizontal: center; }
    ImportModal Button { margin: 0 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[b]Importar pasta[/] — vira alvo (com Dockerfile) ou ferramenta:")
            yield Input(placeholder="/caminho/para/a/pasta", id="import-path")
            with Horizontal(id="row"):
                yield Button("→ alvo (Dockerfile)", id="as-target", variant="primary")
                yield Button("→ ferramenta", id="as-tool", variant="success")
                yield Button("cancelar", id="cancel", variant="default")

    def _collect(self, kind: str) -> None:
        path = self.query_one("#import-path", Input).value.strip()
        if path:
            self.dismiss((kind, path))

    @on(Button.Pressed, "#as-target")
    def _as_target(self) -> None:
        self._collect("target")

    @on(Button.Pressed, "#as-tool")
    def _as_tool(self) -> None:
        self._collect("tool")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Confirmação simples sim/não."""

    BINDINGS = [Binding("escape", "no", "cancelar"), Binding("n", "no"), Binding("y", "yes")]

    CSS = """
    ConfirmModal { align: center middle; }
    ConfirmModal #dialog {
        width: 60; height: auto; border: round #ff5f5f;
        background: $surface; padding: 1 2;
    }
    ConfirmModal #row { height: auto; align-horizontal: center; }
    ConfirmModal Button { margin: 1 2; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._message)
            with Horizontal(id="row"):
                yield Button("destruir", id="yes", variant="error")
                yield Button("cancelar", id="no", variant="primary")

    @on(Button.Pressed, "#yes")
    def _yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def _no(self) -> None:
        self.dismiss(False)

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


# ------------------------------------------------------------------------ app
class CyberLabApp(App[None]):
    TITLE = "CyberLab"
    SUB_TITLE = f"v{__version__} · laboratório de pentest isolado"

    BINDINGS = [
        Binding("ctrl+q", "quit_app", "sair", priority=True),
        Binding("f2", "toggle_focus", "alternar foco", priority=True),
        Binding("ctrl+n", "new_target", "novo alvo"),
        Binding("s", "start_stop", "ligar/desligar"),
        Binding("x", "destroy", "destruir"),
        Binding("a", "import", "importar pasta"),
        Binding("i", "toggle_internet", "internet atacante"),
        Binding("u", "update", "atualizar app"),
    ]

    CSS = """
    #top { height: 1fr; }

    #sidebar {
        width: 46;
        height: 1fr;
        border-right: solid #1f3d1f;
        padding: 0 1;
    }
    #machines { height: 1fr; min-height: 4; }
    #buttons {
        height: auto;
        padding: 1 0 0 0;
    }
    #buttons Button {
        width: 100%;
        height: 3;
        margin: 0 0 1 0;
    }

    #center { width: 1fr; height: 1fr; }

    #meters { height: 8; }
    .meter {
        width: 1fr;
        height: 1fr;
        border: round #1f3d1f;
        padding: 0 1;
    }
    .meter .meter-title { color: #00d75f; text-style: bold; }
    Sparkline { height: 1fr; }
    Sparkline > .sparkline--max-color { color: #00ff41; }
    Sparkline > .sparkline--min-color { color: #0a3d14; }

    #terms { height: 1fr; border-top: solid #1f3d1f; }
    TabbedContent { height: 1fr; }
    TabPane { height: 1fr; }
    Terminal { height: 100%; }
    RichLog { height: 100%; background: #0c0c0c; padding: 0 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.manager = LabManager()
        self._open_panes: set[str] = set()
        self._stats_busy = False
        self._last_sig: list | None = None
        self._cpu_hist: list[float] = [0.0]
        self._ram_hist: list[float] = [0.0]
        self._host_cpu_hist: list[float] = [0.0]
        self._host_ram_hist: list[float] = [0.0]
        self._docker_down_logged = False
        self._pending_select: str | None = None  # máquina a selecionar no próximo refresh

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            with Vertical(id="sidebar"):
                yield Label("[b #00ff41]MÁQUINAS[/]  [dim](enter = terminal)[/]")
                yield Label("", id="lab-info")
                table = DataTable(id="machines", cursor_type="row", zebra_stripes=True)
                table.add_column("máquina", key="name")
                table.add_column("tipo", key="kind")
                table.add_column("estado", key="status")
                table.add_column("ip", key="ip")
                table.add_column("cpu%", key="cpu")
                table.add_column("ram", key="mem")
                yield table
                with Vertical(id="buttons"):
                    yield Button("Iniciar", id="btn-start", variant="success")
                    yield Button("Parar", id="btn-stop", variant="warning")
                    yield Button("Novo alvo", id="btn-new", variant="primary")
                    yield Button("Destruir", id="btn-destroy", variant="error")
                    yield Button("Importar…", id="btn-import", variant="default")
                    yield Button("Atualizar", id="btn-update", variant="default")
                    yield Button("Internet: off", id="btn-net")
            with Vertical(id="center"):
                with Horizontal(id="meters"):
                    with Vertical(classes="meter"):
                        yield Label("HOST CPU %", classes="meter-title")
                        yield Label("0%", id="host-cpu-label")
                        yield Sparkline(self._host_cpu_hist, id="spark-host-cpu")
                    with Vertical(classes="meter"):
                        yield Label("HOST RAM", classes="meter-title")
                        yield Label("0 GB", id="host-ram-label")
                        yield Sparkline(self._host_ram_hist, id="spark-host-ram")
                    with Vertical(classes="meter"):
                        yield Label("LAB CPU %", classes="meter-title")
                        yield Label("0%", id="lab-cpu-label")
                        yield Sparkline(self._cpu_hist, id="spark-cpu")
                    with Vertical(classes="meter"):
                        yield Label("LAB RAM MB", classes="meter-title")
                        yield Label("0 MB", id="lab-ram-label")
                        yield Sparkline(self._ram_hist, id="spark-ram")
                with TabbedContent(id="terms"):
                    yield TabPane(
                        "eventos",
                        RichLog(id="events", max_lines=2000, auto_scroll=True),
                        id="pane-events",
                    )
        yield Footer()

    # ----------------------------------------------------------------- ciclo
    def on_mount(self) -> None:
        self._log("inicializando o laboratório…")
        self._setup()
        self.set_interval(1.0, self._tick)

    # ------------------------------------------------------------------ logs
    def _write_log(self, msg: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.query_one("#events", RichLog).write(Text(f"[{stamp}] {msg}"))

    def _log(self, msg: str) -> None:
        """Thread-safe: usável de workers."""
        try:
            self.call_from_thread(self._write_log, msg)
        except RuntimeError:
            self._write_log(msg)

    # ----------------------------------------------------------------- setup
    @work(thread=True)
    def _setup(self) -> None:
        try:
            if not self.manager.ping():
                self._log("[bold red]docker indisponível[/] — verifique o daemon")
                return
            self.manager.ensure_network()
            self._log(f"rede isolada pronta ({self._net_desc()})")
            self.manager.ensure_attacker()
            self._log("máquina atacante pronta")
        except Exception as exc:
            self._log(f"[bold red]falha no setup:[/] {exc}")
            return
        self.call_from_thread(self._after_setup)

    def _after_setup(self) -> None:
        self.open_terminal(ATTACKER_NAME, "/bin/bash", "atacante")
        try:
            self.query_one("#machines", DataTable).focus()
        except Exception:
            pass

    def _net_desc(self) -> str:
        from .manager import NETWORK_NAME, SUBNET

        return f"{NETWORK_NAME} {SUBNET} (internal)"

    # -------------------------------------------------------------- métricas
    def _tick(self) -> None:
        if self._stats_busy:
            return
        self._stats_busy = True
        self.run_worker(self._collect_stats, thread=True, group="stats", exclusive=True)

    def _collect_stats(self) -> None:
        try:
            machines = self.manager.machines()
            stats = self.manager.sample_stats()
            host = self.manager.host_stats()
        except Exception as exc:
            self._stats_busy = False
            if not self._docker_down_logged:
                self._docker_down_logged = True
                self._log(f"[bold red]docker indisponível:[/] {exc}")
            return
        self._docker_down_logged = False
        self._stats_busy = False
        try:
            self.call_from_thread(self._apply_stats, machines, stats, host)
        except RuntimeError:
            pass  # app já encerrou

    def _apply_stats(self, machines: list[Machine], stats: dict, host: dict) -> None:
        try:
            self._apply_stats_inner(machines, stats, host)
        except Exception:
            import traceback

            self._write_log("[bold red]erro ao atualizar painéis:[/]\n" + traceback.format_exc())

    def _apply_stats_inner(self, machines: list[Machine], stats: dict, host: dict) -> None:
        self._last_machines = machines
        sig = [(m.name, m.status, m.internet) for m in machines]

        table = self.query_one("#machines", DataTable)
        if sig != self._last_sig:
            names = [m.name for m in machines]
            selected = self._selected_name()
            # prioridade: máquina recém-criada via UI deve ficar selecionada
            if self._pending_select in names:
                selected = self._pending_select
            self._pending_select = None
            table.clear()
            for m in machines:
                table.add_row(*self._row_cells(m, stats.get(m.name)), key=m.name)
            self._last_sig = sig
            if selected and selected in names:
                table.move_cursor(row=names.index(selected), animate=False)
        else:
            for m in machines:
                cpu, mem, _limit = stats.get(m.name, (0.0, 0.0, 0.0))
                try:
                    table.update_cell(m.name, "cpu", f"{cpu:.1f}")
                    table.update_cell(m.name, "mem", _fmt_mb(mem))
                except Exception:
                    pass

        # medidores
        total_cpu = sum(v[0] for v in stats.values())
        total_mem = sum(v[1] for v in stats.values())
        running = sum(1 for m in machines if m.status == "running")
        host_cpu = host.get("cpu", 0.0)
        host_ram_gb = host.get("mem_used_gb", 0.0)

        self._cpu_hist.append(total_cpu)
        self._ram_hist.append(total_mem)
        self._host_cpu_hist.append(host_cpu)
        self._host_ram_hist.append(host_ram_gb)
        for hist in (self._cpu_hist, self._ram_hist, self._host_cpu_hist, self._host_ram_hist):
            del hist[:-180]

        try:
            self.query_one("#spark-cpu", Sparkline).data = list(self._cpu_hist)
            self.query_one("#spark-ram", Sparkline).data = list(self._ram_hist)
            self.query_one("#spark-host-cpu", Sparkline).data = list(self._host_cpu_hist)
            self.query_one("#spark-host-ram", Sparkline).data = list(self._host_ram_hist)
        except Exception:
            pass
        for spark in self.query(Sparkline):
            spark.refresh()

        self.query_one("#lab-cpu-label", Label).update(f"{total_cpu:.1f}%")
        self.query_one("#lab-ram-label", Label).update(f"{total_mem:.0f} MB")
        self.query_one("#host-cpu-label", Label).update(f"{host_cpu:.0f}%")
        self.query_one("#host-ram-label", Label).update(f"{host_ram_gb:.1f} GB")

        try:
            internet = self.manager.internet_enabled()
        except Exception:
            internet = False
        self.query_one("#lab-info", Label).update(
            f"[dim]{running}/{len(machines)} ativas · internet "
            f"{'[bold #00ff41]ON[/]' if internet else '[dim]off[/]'}[/]"
        )
        btn_net = self.query_one("#btn-net", Button)
        btn_net.label = "Internet: ON" if internet else "Internet: off"

    @staticmethod
    def _row_cells(m: Machine, stat) -> tuple:
        cpu, mem, _limit = stat or (0.0, 0.0, 0.0)
        dot = "[green]●[/]" if m.status == "running" else "[red]○[/]"
        return (
            Text.from_markup(m.name.replace("cyberlab-", "")),
            m.kind,
            Text.from_markup(f"{dot} {m.status}"),
            m.ip,
            f"{cpu:.1f}",
            _fmt_mb(mem),
        )

    def _selected_name(self) -> str | None:
        table = self.query_one("#machines", DataTable)
        try:
            if table.row_count == 0:
                return None
            row = table.ordered_rows[table.cursor_row]
            return str(row.key.value)
        except Exception:
            return None

    # -------------------------------------------------------------- terminais
    def open_terminal(self, name: str, shell: str, title: str) -> None:
        pane_id = f"pane-{name}"
        tabs = self.query_one("#terms", TabbedContent)

        async def _open() -> None:
            if pane_id in self._open_panes:
                tabs.active = pane_id
                return
            term = Terminal(["docker", "exec", "-it", name, shell], title=title)
            await tabs.add_pane(TabPane(title, term, id=pane_id))
            self._open_panes.add(pane_id)
            tabs.active = pane_id

        self.run_worker(_open(), group="tabs")

    def _close_pane(self, pane_id: str) -> None:
        tabs = self.query_one("#terms", TabbedContent)

        async def _rm() -> None:
            try:
                await tabs.remove_pane(pane_id)
            except Exception:
                pass
            self._open_panes.discard(pane_id)

        self.run_worker(_rm(), group="tabs")

    # ------------------------------------------------------------------ ações
    @on(DataTable.RowSelected, "#machines")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        name = str(event.row_key.value)
        kind = next((m.kind for m in self._machines_cache if m.name == name), "attacker")
        self.open_terminal(name, _shell_for(kind), name.replace("cyberlab-", ""))

    @property
    def _machines_cache(self) -> list[Machine]:
        return getattr(self, "_last_machines", [])

    def action_new_target(self) -> None:
        def _spawn(kind: str | None) -> None:
            if kind:
                self._spawn_target(kind)

        self.push_screen(TargetModal(self.manager.all_targets()), _spawn)

    @on(Button.Pressed, "#btn-new")
    def _btn_new(self) -> None:
        self.action_new_target()

    # ---- importação de pastas (alvo/ferramenta) via TUI
    def action_import(self) -> None:
        def _done(result: tuple[str, str] | None) -> None:
            if not result:
                return
            kind, path = result
            if kind == "target":
                self._import_target(path)
            else:
                self._import_tool(path)

        self.push_screen(ImportModal(), _done)

    @on(Button.Pressed, "#btn-import")
    def _btn_import(self) -> None:
        self.action_import()

    @work(thread=True)
    def _import_target(self, path: str) -> None:
        self._log(f"[build] compilando alvo de '{path}'…")
        try:
            name = self.manager.add_target(path)
        except Exception as exc:
            self._log(f"[bold red]falha ao compilar alvo:[/] {exc}")
            return
        self._log(f"alvo custom [green]{name}[/] pronto — use 'novo alvo' para lançá-lo")

    @work(thread=True)
    def _import_tool(self, path: str) -> None:
        self._log(f"sincronizando ferramenta de '{path}'…")
        try:
            name = self.manager.add_tool(path)
        except Exception as exc:
            self._log(f"[bold red]falha ao importar ferramenta:[/] {exc}")
            return
        self._log(f"ferramenta [green]{name}[/] disponível em /root/tools/{name} (atacante)")

    # ---- atualização do próprio app (sem desinstalar)
    def action_update(self) -> None:
        self._update_app()

    @on(Button.Pressed, "#btn-update")
    def _btn_update(self) -> None:
        self.action_update()

    @work(thread=True)
    def _update_app(self) -> None:
        self._log("[bold cyan]atualizando o app…[/] (pode levar alguns minutos)")
        self_update(log=self._log)
        self._log("[bold green]atualização concluída[/] — saia (ctrl+q) e abra o cyberlab_py de novo")

    @work(thread=True)
    def _spawn_target(self, kind: str) -> None:
        self._log(f"criando alvo '{kind}'…")
        try:
            name = self.manager.spawn_target(kind)
        except Exception as exc:
            self._log(f"[bold red]falha ao criar alvo:[/] {exc}")
            return
        self._log(f"alvo [green]{name}[/] no ar — abrindo terminal")
        self._pending_select = name
        self.call_from_thread(
            self.open_terminal, name, _shell_for(kind), name.replace("cyberlab-", "")
        )

    def action_start_stop(self) -> None:
        name = self._selected_name()
        if name:
            self._toggle_machine(name)

    @work(thread=True)
    def _toggle_machine(self, name: str) -> None:
        """Decide start/stop consultando o Docker na hora (sem cache)."""
        try:
            cur = next((m for m in self.manager.machines() if m.name == name), None)
            if cur is None:
                return
            if cur.status == "running":
                self.manager.stop(name)
                self._log(f"[yellow]■[/] {name} parado")
            else:
                self.manager.start(name)
                self._log(f"[green]▶[/] {name} iniciado")
        except Exception as exc:
            self._log(f"[red]falha ao alternar {name}:[/] {exc}")

    @on(Button.Pressed, "#btn-start")
    def _btn_start(self) -> None:
        name = self._selected_name()
        if name:
            self._start_machine(name)

    @on(Button.Pressed, "#btn-stop")
    def _btn_stop(self) -> None:
        name = self._selected_name()
        if name:
            self._stop_machine(name)

    @work(thread=True)
    def _start_machine(self, name: str) -> None:
        try:
            self.manager.start(name)
            self._log(f"[green]▶[/] {name} iniciado")
        except Exception as exc:
            self._log(f"[red]falha ao iniciar {name}:[/] {exc}")

    @work(thread=True)
    def _stop_machine(self, name: str) -> None:
        try:
            self.manager.stop(name)
            self._log(f"[yellow]■[/] {name} parado")
        except Exception as exc:
            self._log(f"[red]falha ao parar {name}:[/] {exc}")

    def action_destroy(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if name == ATTACKER_NAME:
            self._log("[yellow]a máquina atacante não pode ser destruída por aqui[/]")
            return
        self.push_screen(
            ConfirmModal(f"Destruir [b]{name}[/b]? (remoção definitiva)"),
            lambda ok: ok and self._do_destroy(name),
        )

    @on(Button.Pressed, "#btn-destroy")
    def _btn_destroy(self) -> None:
        self.action_destroy()

    @work(thread=True)
    def _do_destroy(self, name: str) -> None:
        try:
            self.manager.destroy(name)
            self._log(f"[red]✖[/] {name} destruído")
            self.call_from_thread(self._close_pane, f"pane-{name}")
        except Exception as exc:
            self._log(f"[red]falha ao destruir {name}:[/] {exc}")

    def action_toggle_internet(self) -> None:
        self._toggle_internet()

    @on(Button.Pressed, "#btn-net")
    def _btn_net(self) -> None:
        self.action_toggle_internet()

    @work(thread=True)
    def _toggle_internet(self) -> None:
        try:
            enabled = self.manager.set_internet(not self.manager.internet_enabled())
        except Exception as exc:
            self._log(f"[red]falha ao alternar internet:[/] {exc}")
            return
        state = "[green]HABILITADA[/] (NAT para fora)" if enabled else "[dim]desabilitada (isolado)[/]"
        self._log(f"internet do atacante: {state}")

    # ------------------------------------------------------------------ misc
    def action_toggle_focus(self) -> None:
        tabs = self.query_one("#terms", TabbedContent)
        active = tabs.active_pane
        focused = self.focused
        if isinstance(focused, Terminal):
            self.query_one("#machines", DataTable).focus()
        elif active is not None:
            for child in active.query(Terminal):
                child.focus()
                return
            self.query_one("#machines", DataTable).focus()

    def action_quit_app(self) -> None:
        self.exit()

    def on_unmount(self) -> None:
        # mata PTYs remanescentes
        for term in self.query(Terminal):
            term.on_unmount()


def _fmt_mb(mb: float) -> str:
    return f"{mb:.0f}M" if mb < 1024 else f"{mb / 1024:.1f}G"
