from __future__ import annotations

import time
from pathlib import Path
from typing import cast

import mido
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
    Static,
    Switch,
)

from .config import load_config, save_config
from .engine import MidiEngine, MidiEvent, list_input_ports, list_output_ports
from .models import AppConfig, DeviceConfig, Mapping, MessageType

MESSAGE_TYPES = [
    ("program_change", "program_change"),
    ("control_change", "control_change"),
    ("note_on", "note_on"),
    ("note_off", "note_off"),
    ("sysex", "sysex"),
]


# ---------------------------------------------------------------------------
# Device Modal
# ---------------------------------------------------------------------------

class DeviceModal(ModalScreen[DeviceConfig | None]):
    """Add / edit a device."""

    DEFAULT_CSS = """
    DeviceModal {
        align: center middle;
    }
    DeviceModal > Vertical {
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    DeviceModal .field-label { margin-top: 1; }
    DeviceModal .buttons { margin-top: 1; }
    """

    def __init__(self, existing: DeviceConfig | None = None) -> None:
        super().__init__()
        self._existing = existing
        self._all_in = list_input_ports()
        self._all_out = list_output_ports()

    def _port_options(self, direction: str) -> list[tuple[str, str]]:
        ports = self._all_in if direction == "input" else self._all_out
        return [(p, p) for p in ports] if ports else [("(no ports found)", "")]

    def compose(self) -> ComposeResult:
        dev = self._existing
        initial_direction = dev.direction if dev else "input"
        port_options = self._port_options(initial_direction)

        with Vertical():
            yield Label("Device Name", classes="field-label")
            yield Input(value=dev.name if dev else "", id="dev-name", placeholder="e.g. launchpad")
            yield Label("Direction", classes="field-label")
            with RadioSet(id="dev-direction"):
                yield RadioButton("Input", value=not dev or dev.direction == "input", id="dir-input")
                yield RadioButton("Output", value=bool(dev and dev.direction == "output"), id="dir-output")
            yield Label("Port", classes="field-label")
            yield Select(port_options, value=dev.port if dev else Select.NULL, id="dev-port", allow_blank=True)
            with Horizontal(classes="buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    @on(RadioSet.Changed, "#dev-direction")
    def _direction_changed(self, event: RadioSet.Changed) -> None:
        direction = "input" if event.radio_set.pressed_index == 0 else "output"
        self.query_one("#dev-port", Select).set_options(self._port_options(direction))

    @on(Select.Changed, "#dev-port")
    def _port_selected(self, event: Select.Changed) -> None:
        if event.value and event.value != Select.NULL:
            name_input = self.query_one("#dev-name", Input)
            if not name_input.value.strip():
                # Sanitize: widget IDs may only contain letters, digits, hyphens, underscores
                import re
                name_input.value = re.sub(r"[^a-zA-Z0-9_-]", "-", str(event.value))

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        name = self.query_one("#dev-name", Input).value.strip()
        port_widget = self.query_one("#dev-port", Select)
        port = port_widget.value if port_widget.value != Select.NULL else ""
        radio = self.query_one("#dev-direction", RadioSet)
        direction = "input" if radio.pressed_index == 0 else "output"

        if not name or not port:
            return

        self.dismiss(DeviceConfig(name=name, port=port, direction=direction))

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Mapping Modal
# ---------------------------------------------------------------------------

class MappingModal(ModalScreen[Mapping | None]):
    """Add / edit a mapping."""

    DEFAULT_CSS = """
    MappingModal {
        align: center middle;
    }
    MappingModal > Vertical {
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        width: 70;
        height: auto;
        max-height: 90vh;
    }
    MappingModal ScrollableContainer { height: 1fr; }
    MappingModal .field-label { margin-top: 1; }
    MappingModal .buttons { margin-top: 1; }
    MappingModal .row { height: auto; }
    MappingModal #momentary-section { display: none; }
    MappingModal #momentary-section.visible { display: block; }
    """

    def __init__(self, config: AppConfig, existing: Mapping | None = None) -> None:
        super().__init__()
        self._config = config
        self._existing = existing

    def _device_options(self, direction: str) -> list[tuple[str, str]]:
        opts = [
            (name, name)
            for name, dev in self._config.devices.items()
            if dev.direction == direction
        ]
        return opts or [("(none)", "")]

    def compose(self) -> ComposeResult:
        m = self._existing
        in_opts = self._device_options("input")
        out_opts = self._device_options("output")

        with Vertical():
            yield Label("Mapping Name", classes="field-label")
            yield Input(value=m.name if m else "", id="map-name", placeholder="e.g. Patch select -> CC")

            with ScrollableContainer():
                yield Label("Input Device", classes="field-label")
                yield Select(in_opts, value=m.input_device if m else Select.NULL, id="map-in-device", allow_blank=True)

                yield Label("Input Type", classes="field-label")
                yield Select(MESSAGE_TYPES, value=m.input_type if m else "program_change", id="map-in-type")

                yield Label("Input Channel (1–16)", classes="field-label")
                yield Input(value=str(m.input_channel if m else 1), id="map-in-ch")

                yield Label("Input Value (-1 = any)", classes="field-label")
                yield Input(value=str(m.input_value if m else -1), id="map-in-val")

                yield Label("Output Device", classes="field-label")
                yield Select(out_opts, value=m.output_device if m else Select.NULL, id="map-out-device", allow_blank=True)

                yield Label("Output Type", classes="field-label")
                yield Select(MESSAGE_TYPES, value=m.output_type if m else "control_change", id="map-out-type")

                yield Label("Output Channel (1–16)", classes="field-label")
                yield Input(value=str(m.output_channel if m else 1), id="map-out-ch")

                yield Label("Output Control / Note number", classes="field-label")
                yield Input(value=str(m.output_control if m else 0), id="map-out-ctrl")

                yield Label("Output Value", classes="field-label")
                yield Input(value=str(m.output_value if m else 127), id="map-out-val")

                with Horizontal(classes="row"):
                    yield Label("Momentary: ", classes="field-label")
                    yield Switch(value=m.momentary if m else False, id="map-momentary")

                with Vertical(id="momentary-section", classes="visible" if (m and m.momentary) else ""):
                    yield Label("Momentary Delay (ms)", classes="field-label")
                    yield Input(value=str(m.momentary_delay_ms if m else 100), id="map-delay")

            with Horizontal(classes="buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    @on(Switch.Changed, "#map-momentary")
    def _toggle_momentary(self, event: Switch.Changed) -> None:
        section = self.query_one("#momentary-section")
        if event.value:
            section.add_class("visible")
        else:
            section.remove_class("visible")

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        def _int(widget_id: str, default: int) -> int:
            try:
                return int(self.query_one(widget_id, Input).value)
            except (ValueError, TypeError):
                return default

        def _select(widget_id: str) -> str:
            v = self.query_one(widget_id, Select).value
            return v if v != Select.NULL else ""

        name = self.query_one("#map-name", Input).value.strip()
        momentary = self.query_one("#map-momentary", Switch).value

        m = Mapping(
            name=name,
            input_device=_select("#map-in-device"),
            input_type=cast(MessageType, _select("#map-in-type") or "program_change"),
            input_channel=_int("#map-in-ch", 1),
            input_value=_int("#map-in-val", -1),
            output_device=_select("#map-out-device"),
            output_type=cast(MessageType, _select("#map-out-type") or "control_change"),
            output_channel=_int("#map-out-ch", 1),
            output_control=_int("#map-out-ctrl", 0),
            output_value=_int("#map-out-val", 127),
            momentary=momentary,
            momentary_delay_ms=_int("#map-delay", 100),
        )
        self.dismiss(m)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Device Row
# ---------------------------------------------------------------------------

class DeviceRow(Horizontal):
    DEFAULT_CSS = """
    DeviceRow {
        height: 1;
        margin: 0;
    }
    DeviceRow Label { width: 1fr; }
    DeviceRow Button { min-width: 3; height: 1; }
    """

    def __init__(self, name: str, dev: DeviceConfig) -> None:
        super().__init__(classes="device-row")
        self._dev_name = name
        self._dev = dev

    def compose(self) -> ComposeResult:
        yield Label(f"{self._dev_name}  [{self._dev.direction}]")
        yield Button("X", id=f"del-dev-{self._dev_name}", classes="del-btn", variant="error")


# ---------------------------------------------------------------------------
# Device Panel
# ---------------------------------------------------------------------------

class DevicePanel(Vertical):
    DEFAULT_CSS = """
    DevicePanel {
        border: solid $primary;
        padding: 0 1;
        width: 35;
    }
    DevicePanel .panel-title {
        text-style: bold;
        background: $primary;
        padding: 0 1;
    }
    DevicePanel .device-row {
        height: 1;
        margin: 0;
    }
    DevicePanel .device-row Label {
        width: 1fr;
    }
    DevicePanel Button.del-btn {
        min-width: 3;
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Devices", classes="panel-title")
        yield Button("[+] Add Device", id="add-device", variant="success")
        yield Vertical(id="device-list")

    def refresh_devices(self, config: AppConfig) -> None:
        device_list = self.query_one("#device-list", Vertical)
        device_list.remove_children()
        for name, dev in config.devices.items():
            device_list.mount(DeviceRow(name, dev))


# ---------------------------------------------------------------------------
# Mapping Panel
# ---------------------------------------------------------------------------

class MappingPanel(Vertical):
    DEFAULT_CSS = """
    MappingPanel {
        border: solid $primary;
        padding: 0 1;
        width: 1fr;
    }
    MappingPanel .panel-title {
        text-style: bold;
        background: $primary;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Mappings", classes="panel-title")
        yield Button("[+] Add Mapping", id="add-mapping", variant="success")
        yield DataTable(id="mapping-table", show_cursor=True)

    def on_mount(self) -> None:
        table = self.query_one("#mapping-table", DataTable)
        table.add_columns("Name", "Input Device", "Output Device", "Type", "Edit", "Del")

    def refresh_mappings(self, config: AppConfig) -> None:
        table = self.query_one("#mapping-table", DataTable)
        table.clear()
        for i, m in enumerate(config.mappings):
            table.add_row(
                m.name,
                m.input_device,
                m.output_device,
                f"{m.input_type}→{m.output_type}",
                "[Edit]",
                "[X]",
                key=str(i),
            )


# ---------------------------------------------------------------------------
# Monitor Panel
# ---------------------------------------------------------------------------

class MonitorPanel(Vertical):
    DEFAULT_CSS = """
    MonitorPanel {
        border: solid $primary;
        height: 12;
        padding: 0 1;
    }
    MonitorPanel .panel-title {
        text-style: bold;
        background: $primary;
        padding: 0 1;
    }
    MonitorPanel RichLog {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("MIDI Monitor", classes="panel-title")
        yield RichLog(id="monitor-log", highlight=True, markup=True, auto_scroll=True)

    def log_event(self, event: MidiEvent) -> None:
        log = self.query_one("#monitor-log", RichLog)
        ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
        msg = event.message
        matched_style = "bold " if event.matched else ""

        if event.direction == "IN":
            color = "cyan"
        else:
            color = "green"

        details = _format_msg(msg)
        line = (
            f"[dim]{ts}[/dim]  "
            f"[{matched_style}{color}]{event.direction:3}[/{matched_style}{color}]  "
            f"[white]{event.device_name:<16}[/white]  "
            f"{details}"
        )
        log.write(line)


def _format_msg(msg: mido.Message) -> str:
    t = msg.type
    if t == "program_change":
        return f"[yellow]program_change[/yellow]  ch={msg.channel + 1}  prog={msg.program}"
    elif t == "control_change":
        return f"[magenta]control_change[/magenta]  ch={msg.channel + 1}  ctrl={msg.control}  val={msg.value}"
    elif t in ("note_on", "note_off"):
        return f"[blue]{t}[/blue]  ch={msg.channel + 1}  note={msg.note}  vel={msg.velocity}"
    elif t == "sysex":
        raw = bytes(msg.data[:8]).hex()
        return f"[red]sysex[/red]  {raw}{'…' if len(msg.data) > 8 else ''}"
    else:
        return str(msg)


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class MidiBridgeApp(App):
    TITLE = "MIDI Bridge"
    BINDINGS = [
        Binding("s", "save_config", "Save"),
        Binding("q", "quit", "Quit"),
    ]
    CSS = """
    Screen {
        layout: vertical;
    }
    #top-row {
        layout: horizontal;
        height: 1fr;
    }
    """

    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self._config_path = config_path
        self._config = load_config(config_path)
        self._engine = MidiEngine(self._config, self._on_midi_event)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._engine.start()
        self._refresh_panels()

    def on_unmount(self) -> None:
        self._engine.stop()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top-row"):
            yield DevicePanel(id="device-panel")
            yield MappingPanel(id="mapping-panel")
        yield MonitorPanel(id="monitor-panel")
        yield Footer()

    # ------------------------------------------------------------------
    # MIDI event callback (called from engine threads)
    # ------------------------------------------------------------------

    def _on_midi_event(self, event: MidiEvent) -> None:
        self.call_from_thread(self._post_midi_event, event)

    def _post_midi_event(self, event: MidiEvent) -> None:
        self.query_one("#monitor-panel", MonitorPanel).log_event(event)

    # ------------------------------------------------------------------
    # Panel refresh helpers
    # ------------------------------------------------------------------

    def _refresh_panels(self) -> None:
        self.query_one("#device-panel", DevicePanel).refresh_devices(self._config)
        self.query_one("#mapping-panel", MappingPanel).refresh_mappings(self._config)

    def _update_config(self, config: AppConfig) -> None:
        self._config = config
        self._engine.reload(config)
        self._refresh_panels()

    # ------------------------------------------------------------------
    # Button / table interactions
    # ------------------------------------------------------------------

    @on(Button.Pressed, "#add-device")
    @work
    async def _add_device(self) -> None:
        result: DeviceConfig | None = await self.push_screen_wait(DeviceModal())
        if result is None:
            return
        new_devices = dict(self._config.devices)
        new_devices[result.name] = result
        self._update_config(AppConfig(devices=new_devices, mappings=list(self._config.mappings)))

    @on(Button.Pressed, "#add-mapping")
    @work
    async def _add_mapping(self) -> None:
        result: Mapping | None = await self.push_screen_wait(MappingModal(self._config))
        if result is None:
            return
        new_mappings = list(self._config.mappings) + [result]
        self._update_config(AppConfig(devices=dict(self._config.devices), mappings=new_mappings))

    @on(Button.Pressed)
    async def _handle_dynamic_buttons(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id.startswith("del-dev-"):
            name = btn_id[len("del-dev-"):]
            new_devices = {k: v for k, v in self._config.devices.items() if k != name}
            self._update_config(AppConfig(devices=new_devices, mappings=list(self._config.mappings)))

    @on(DataTable.CellSelected, "#mapping-table")
    @work
    async def _mapping_table_cell(self, event: DataTable.CellSelected) -> None:
        table = self.query_one("#mapping-table", DataTable)
        row_key = event.cell_key.row_key.value
        col_index = event.coordinate.column

        # Column 4 = Edit, Column 5 = Delete
        if col_index == 4:
            idx = int(row_key)
            existing = self._config.mappings[idx]
            result: Mapping | None = await self.push_screen_wait(MappingModal(self._config, existing))
            if result is None:
                return
            new_mappings = list(self._config.mappings)
            new_mappings[idx] = result
            self._update_config(AppConfig(devices=dict(self._config.devices), mappings=new_mappings))
        elif col_index == 5:
            idx = int(row_key)
            new_mappings = [m for i, m in enumerate(self._config.mappings) if i != idx]
            self._update_config(AppConfig(devices=dict(self._config.devices), mappings=new_mappings))

    # ------------------------------------------------------------------
    # Key actions
    # ------------------------------------------------------------------

    def action_save_config(self) -> None:
        save_config(self._config, self._config_path)
        self.notify(f"Saved to {self._config_path}", title="Saved")

    def action_quit(self) -> None:
        self.exit()
