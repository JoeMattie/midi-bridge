from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import cast

import mido
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
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
    ("PC", "program_change"),
    ("CC", "control_change"),
    ("Note On", "note_on"),
    ("Note Off", "note_off"),
    ("SysEx", "sysex"),
]

_TYPE_ABBR = {
    "program_change": "PC",
    "control_change": "CC",
    "note_on": "Note On",
    "note_off": "Note Off",
    "sysex": "SysEx",
}


# ---------------------------------------------------------------------------
# Device Modal
# ---------------------------------------------------------------------------

class DeviceModal(ModalScreen[DeviceConfig | None]):
    """Add / edit a device."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

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
                name_input.value = str(event.value)

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

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.action_cancel()


# ---------------------------------------------------------------------------
# Mapping Modal
# ---------------------------------------------------------------------------

class MappingModal(ModalScreen[Mapping | None]):
    """Add / edit a mapping."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

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
        in_val = m.input_device if m and m.input_device in dict(in_opts) else Select.NULL
        out_val = m.output_device if m and m.output_device in dict(out_opts) else Select.NULL

        ok_disabled = not (m and m.name and m.input_device and m.output_device)
        with Vertical():
            with Horizontal(classes="buttons"):
                yield Input(value=m.name if m else "", id="map-name", placeholder="Mapping name…")
                yield Button("OK", variant="primary", id="ok", disabled=ok_disabled)
                yield Button("Cancel", id="cancel")

            # -- Listen row (above both columns) --
            with Horizontal(classes="listen-row"):
                yield Button("Listen for MIDI…", id="listen-btn", variant="warning")

            # -- Two-column layout: Input | Output --
            with Horizontal(classes="columns"):
                with Vertical(classes="col"):
                    yield Static("Input", classes="col-title")
                    yield Label("Device", classes="field-label")
                    yield Select(in_opts, value=in_val, id="map-in-device", allow_blank=True)
                    with Horizontal(classes="sub-row"):
                        with Vertical(classes="third-col"):
                            yield Label("Type", classes="field-label")
                            yield Select(MESSAGE_TYPES, value=m.input_type if m else "program_change", id="map-in-type")
                        with Vertical(classes="third-col"):
                            yield Label("Chan", classes="field-label")
                            yield Input(value=str(m.input_channel if m else 1), id="map-in-ch")
                        with Vertical(classes="third-col"):
                            yield Label("Val (-1)", classes="field-label")
                            yield Input(value=str(m.input_value if m else -1), id="map-in-val")

                with Vertical(classes="col"):
                    yield Static("Output", classes="col-title")
                    yield Label("Device", classes="field-label")
                    yield Select(out_opts, value=out_val, id="map-out-device", allow_blank=True)
                    with Horizontal(classes="sub-row"):
                        with Vertical(classes="third-col"):
                            yield Label("Type", classes="field-label")
                            yield Select(MESSAGE_TYPES, value=m.output_type if m else "control_change", id="map-out-type")
                        with Vertical(classes="third-col"):
                            yield Label("Chan", classes="field-label")
                            yield Input(value=str(m.output_channel if m else 1), id="map-out-ch")
                        with Vertical(classes="third-col"):
                            yield Label("CC/Note", classes="field-label")
                            yield Input(value=str(m.output_control if m else 0), id="map-out-ctrl")
                    with Horizontal(classes="sub-row"):
                        with Vertical(classes="half-col"):
                            yield Label("Value", classes="field-label")
                            with RadioSet(id="map-out-val-mode"):
                                yield RadioButton("Fixed", value=not m or m.output_value_mode == "fixed", id="val-fixed")
                                yield RadioButton("Pass", value=bool(m and m.output_value_mode == "passthrough"), id="val-passthrough")
                            with Vertical(id="fixed-value-section", classes="visible" if (not m or m.output_value_mode == "fixed") else ""):
                                yield Input(value=str(m.output_value if m else 127), id="map-out-val")
                        with Vertical(classes="half-col momentary-col"):
                            yield Label("Momentary", classes="field-label")
                            yield Switch(value=m.momentary if m else False, id="map-momentary")
                            with Vertical(id="momentary-section", classes="visible" if (m and m.momentary) else ""):
                                yield Label("Delay (ms)", classes="field-label")
                                yield Input(value=str(m.momentary_delay_ms if m else 100), id="map-delay")

    def on_mount(self) -> None:
        self.query_one("#listen-btn", Button).tooltip = (
            "Click to capture the next incoming MIDI event and auto-fill the input fields"
        )
        self.query_one("#map-in-ch", Input).tooltip = "Channel 1–16"
        self.query_one("#map-out-ch", Input).tooltip = "Channel 1–16"
        self._validate_ok()

    def _validate_ok(self) -> None:
        name = self.query_one("#map-name", Input).value.strip()
        in_dev = self.query_one("#map-in-device", Select).value
        out_dev = self.query_one("#map-out-device", Select).value
        ok = bool(name and in_dev != Select.NULL and in_dev and out_dev != Select.NULL and out_dev)
        self.query_one("#ok", Button).disabled = not ok

    @on(Input.Changed, "#map-name")
    def _name_changed(self) -> None:
        self._validate_ok()

    @on(Select.Changed, "#map-in-device")
    @on(Select.Changed, "#map-out-device")
    def _device_changed(self) -> None:
        self._validate_ok()

    @on(Button.Pressed, "#listen-btn")
    @work
    async def _listen(self) -> None:
        btn = self.query_one("#listen-btn", Button)
        btn.label = "Waiting for MIDI input…"
        btn.disabled = True
        try:
            app = cast(MidiBridgeApp, self.app)
            event = await app.listen_for_event()
            self._populate_from_event(event)
        except asyncio.CancelledError:
            pass
        finally:
            btn.label = "Listen for MIDI…"
            btn.disabled = False

    def _populate_from_event(self, event: MidiEvent) -> None:
        msg = event.message
        t = msg.type

        # Input device
        in_select = self.query_one("#map-in-device", Select)
        in_opts = dict(self._device_options("input"))
        if event.device_name in in_opts:
            in_select.value = event.device_name

        # Input type
        if t in ("program_change", "control_change", "note_on", "note_off", "sysex"):
            self.query_one("#map-in-type", Select).value = t

        # Input channel
        if hasattr(msg, "channel"):
            self.query_one("#map-in-ch", Input).value = str(msg.channel + 1)

        # Input value
        if t == "program_change":
            self.query_one("#map-in-val", Input).value = str(msg.program)
        elif t == "control_change":
            self.query_one("#map-in-val", Input).value = str(msg.control)
        elif t in ("note_on", "note_off"):
            self.query_one("#map-in-val", Input).value = str(msg.note)

    @on(RadioSet.Changed, "#map-out-val-mode")
    def _toggle_value_mode(self, event: RadioSet.Changed) -> None:
        section = self.query_one("#fixed-value-section")
        if event.radio_set.pressed_index == 0:  # Fixed
            section.add_class("visible")
        else:
            section.remove_class("visible")

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
        val_mode_radio = self.query_one("#map-out-val-mode", RadioSet)
        output_value_mode = "fixed" if val_mode_radio.pressed_index == 0 else "passthrough"

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
            output_value_mode=output_value_mode,
            momentary=momentary,
            momentary_delay_ms=_int("#map-delay", 100),
        )
        self.dismiss(m)

    def action_cancel(self) -> None:
        cast(MidiBridgeApp, self.app).cancel_listen()
        self.dismiss(None)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.action_cancel()


# ---------------------------------------------------------------------------
# Device Row
# ---------------------------------------------------------------------------

class DeviceRow(Horizontal):
    def __init__(self, name: str, dev: DeviceConfig) -> None:
        super().__init__(classes="device-row")
        self._dev_name = name
        self._dev = dev

    def compose(self) -> ComposeResult:
        yield Label(f"{self._dev_name}  [{self._dev.direction}]")
        yield Button("✕", classes="del-btn", variant="error")


# ---------------------------------------------------------------------------
# Device Panel
# ---------------------------------------------------------------------------

class DevicePanel(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="panel-header"):
            yield Static("Devices", classes="panel-title")
            yield Button("[+] Add", id="add-device", variant="success")
        yield Vertical(id="device-list")

    def refresh_devices(self, config: AppConfig) -> None:
        device_list = self.query_one("#device-list", Vertical)
        device_list.remove_children()
        for name, dev in config.devices.items():
            device_list.mount(DeviceRow(name, dev))


# ---------------------------------------------------------------------------
# Mapping Row
# ---------------------------------------------------------------------------

class MappingRow(Horizontal):
    class EditPressed(Message):
        def __init__(self, idx: int) -> None:
            super().__init__()
            self.idx = idx

    class DeletePressed(Message):
        def __init__(self, idx: int) -> None:
            super().__init__()
            self.idx = idx

    def __init__(self, idx: int, m: Mapping) -> None:
        super().__init__(classes="mapping-row")
        self._idx = idx
        self._m = m

    def compose(self) -> ComposeResult:
        type_str = f"{_TYPE_ABBR.get(self._m.input_type, self._m.input_type)}→{_TYPE_ABBR.get(self._m.output_type, self._m.output_type)}"
        yield Label(self._m.name, classes="map-col map-col-name")
        yield Label(self._m.input_device, classes="map-col map-col-device")
        yield Label(self._m.output_device, classes="map-col map-col-device")
        yield Label(type_str, classes="map-col map-col-type")
        yield Button("Edit", classes="map-edit-btn", variant="primary")
        yield Button("✕", classes="map-del-btn", variant="error")

    @on(Button.Pressed, ".map-edit-btn")
    def _edit(self) -> None:
        self.post_message(self.EditPressed(self._idx))

    @on(Button.Pressed, ".map-del-btn")
    def _delete(self) -> None:
        self.post_message(self.DeletePressed(self._idx))


# ---------------------------------------------------------------------------
# Mapping Panel
# ---------------------------------------------------------------------------

class MappingPanel(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="panel-header"):
            yield Static("Mappings", classes="panel-title")
            yield Button("[+] Add", id="add-mapping", variant="success")
        with Horizontal(classes="mapping-col-header"):
            yield Static("Name", classes="map-col map-col-name")
            yield Static("Input", classes="map-col map-col-device")
            yield Static("Output", classes="map-col map-col-device")
            yield Static("Type", classes="map-col map-col-type")
            yield Static("", classes="map-action-spacer")
        yield VerticalScroll(id="mapping-list")

    def refresh_mappings(self, config: AppConfig) -> None:
        container = self.query_one("#mapping-list", VerticalScroll)
        container.remove_children()
        for i, m in enumerate(config.mappings):
            container.mount(MappingRow(i, m))


# ---------------------------------------------------------------------------
# Monitor Panel
# ---------------------------------------------------------------------------

class MonitorPanel(Vertical):
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


# ---------------------------------------------------------------------------
# Mapping Monitor Panel (condensed view)
# ---------------------------------------------------------------------------

class MappingMonitorPanel(Vertical):
    """Condensed monitor showing one line per mapping, updated in-place."""

    _refresh_gen: int = 0

    def compose(self) -> ComposeResult:
        yield Static("Mapping Monitor", classes="panel-title")
        yield Vertical(id="mapping-monitor-list")

    def refresh_rows(self, config: AppConfig) -> None:
        self._refresh_gen += 1
        gen = self._refresh_gen
        container = self.query_one("#mapping-monitor-list", Vertical)
        container.remove_children()
        self._name_to_id: dict[str, str] = {}
        for i, m in enumerate(config.mappings):
            widget_id = f"mm-{gen}-{i}"
            self._name_to_id[m.name] = widget_id
            container.mount(Static("", id=widget_id, classes="mapping-monitor-row"))
        self._update_all_idle(config)

    def _update_all_idle(self, config: AppConfig) -> None:
        for m in config.mappings:
            widget_id = self._name_to_id.get(m.name)
            if not widget_id:
                continue
            try:
                row = self.query_one(f"#{widget_id}", Static)
            except Exception:
                continue
            type_str = f"{_TYPE_ABBR.get(m.input_type, m.input_type)}→{_TYPE_ABBR.get(m.output_type, m.output_type)}"
            row.update(
                f"[dim]--:--:--[/dim]  "
                f"[white]{m.name:<20}[/white]  "
                f"[dim]{type_str}[/dim]  "
                f"[dim]waiting…[/dim]"
            )

    def log_event(self, event: MidiEvent) -> None:
        if not event.matched or not event.mapping_name:
            return
        widget_id = getattr(self, "_name_to_id", {}).get(event.mapping_name)
        if not widget_id:
            return
        try:
            row = self.query_one(f"#{widget_id}", Static)
        except Exception:
            return

        ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
        msg = event.message
        details = _format_msg_short(msg)

        if event.direction == "IN":
            color = "cyan"
        else:
            color = "green"

        row.update(
            f"[dim]{ts}[/dim]  "
            f"[bold white]{event.mapping_name:<20}[/bold white]  "
            f"[{color}]{event.direction:3}[/{color}]  "
            f"{details}"
        )


def _format_msg_short(msg: mido.Message) -> str:
    t = msg.type
    if t == "program_change":
        return f"[yellow]PC[/yellow] ch={msg.channel + 1} prog={msg.program}"
    elif t == "control_change":
        return f"[magenta]CC[/magenta] ch={msg.channel + 1} ctrl={msg.control} val={msg.value}"
    elif t in ("note_on", "note_off"):
        label = "NOn" if t == "note_on" else "NOff"
        return f"[blue]{label}[/blue] ch={msg.channel + 1} note={msg.note} vel={msg.velocity}"
    elif t == "sysex":
        raw = bytes(msg.data[:8]).hex()
        return f"[red]SysEx[/red] {raw}{'…' if len(msg.data) > 8 else ''}"
    else:
        return str(msg)


# ---------------------------------------------------------------------------
# Compact Monitor Panel (small mode — combined IN+OUT on one line)
# ---------------------------------------------------------------------------

_COMPACT_TYPE_ABBR = {
    "program_change": "PC",
    "control_change": "CC",
    "note_on": "NOn",
    "note_off": "NOff",
    "sysex": "SysEx",
}


def _compact_input_str(msg: mido.Message) -> str:
    """Format input side: TYPE:ch.value"""
    abbr = _COMPACT_TYPE_ABBR.get(msg.type, msg.type)
    if msg.type == "program_change":
        return f"{abbr}:{msg.channel + 1}.{msg.program}"
    elif msg.type == "control_change":
        return f"{abbr}:{msg.channel + 1}.{msg.control}"
    elif msg.type in ("note_on", "note_off"):
        return f"{abbr}:{msg.channel + 1}.{msg.note}"
    elif msg.type == "sysex":
        return abbr
    return abbr


def _compact_output_str(msg: mido.Message, out_values: list[int]) -> str:
    """Format output side: TYPE:ctrl.[val,...] or TYPE:ch.prog"""
    abbr = _COMPACT_TYPE_ABBR.get(msg.type, msg.type)
    if msg.type == "control_change":
        vals = ",".join(str(v) for v in out_values) if out_values else str(msg.value)
        return f"{abbr}:{msg.control}.[{vals}]"
    elif msg.type == "program_change":
        return f"{abbr}:{msg.channel + 1}.{msg.program}"
    elif msg.type in ("note_on", "note_off"):
        vals = ",".join(str(v) for v in out_values) if out_values else str(msg.velocity)
        return f"{abbr}:{msg.note}.[{vals}]"
    elif msg.type == "sysex":
        return abbr
    return abbr


class _PendingCompactLine:
    """Buffers a matched IN event and its associated OUT values."""
    __slots__ = ("timestamp", "in_device", "in_msg", "out_device", "out_msg", "out_values", "timer_handle")

    def __init__(self, timestamp: float, in_device: str, in_msg: mido.Message) -> None:
        self.timestamp = timestamp
        self.in_device = in_device
        self.in_msg = in_msg
        self.out_device: str | None = None
        self.out_msg: mido.Message | None = None
        self.out_values: list[int] = []
        self.timer_handle: asyncio.TimerHandle | None = None


def _extract_out_value(msg: mido.Message) -> int:
    t = msg.type
    if t == "control_change":
        return msg.value
    elif t == "program_change":
        return msg.program
    elif t in ("note_on", "note_off"):
        return msg.velocity
    return 0


class CompactMonitorPanel(Vertical):
    """Small-mode monitor: one line per mapping trigger, IN+OUT combined."""

    _FLUSH_DELAY = 0.5  # seconds to wait for momentary follow-ups

    def compose(self) -> ComposeResult:
        yield RichLog(id="compact-log", highlight=True, markup=True, auto_scroll=True)

    def on_mount(self) -> None:
        self._pending: dict[str, _PendingCompactLine] = {}

    def log_event(self, event: MidiEvent) -> None:
        if not event.matched or not event.mapping_name:
            return

        name = event.mapping_name

        if event.direction == "IN":
            # Flush any existing pending line for this mapping
            if name in self._pending:
                self._flush(name)
            pending = _PendingCompactLine(event.timestamp, event.device_name, event.message)
            self._pending[name] = pending
            self._schedule_flush(name)
        elif event.direction == "OUT" and name in self._pending:
            pending = self._pending[name]
            pending.out_device = event.device_name
            pending.out_msg = event.message
            pending.out_values.append(_extract_out_value(event.message))
            # Reset flush timer to wait for more OUT events (momentary)
            self._schedule_flush(name)

    def _schedule_flush(self, name: str) -> None:
        pending = self._pending.get(name)
        if not pending:
            return
        if pending.timer_handle is not None:
            pending.timer_handle.cancel()
        loop = asyncio.get_running_loop()
        pending.timer_handle = loop.call_later(self._FLUSH_DELAY, self._flush, name)

    def _flush(self, name: str) -> None:
        pending = self._pending.pop(name, None)
        if not pending:
            return
        if pending.timer_handle is not None:
            pending.timer_handle.cancel()

        ts = time.strftime("%H:%M:%S", time.localtime(pending.timestamp))
        in_str = _compact_input_str(pending.in_msg)

        if pending.out_msg is not None:
            out_str = _compact_output_str(pending.out_msg, pending.out_values)
            line = (
                f"[dim]{ts}[/dim] "
                f"[cyan]{pending.in_device}[/cyan] "
                f"[white]{in_str}[/white]"
                f" -> "
                f"[green]{pending.out_device}[/green] "
                f"[white]{out_str}[/white]"
            )
        else:
            # IN only, no output arrived
            line = (
                f"[dim]{ts}[/dim] "
                f"[cyan]{pending.in_device}[/cyan] "
                f"[white]{in_str}[/white]"
            )

        self.query_one("#compact-log", RichLog).write(line)


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
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("s", "save_config", "Save"),
        Binding("c", "clear_monitor", "Clear Monitor"),
        Binding("v", "toggle_view", "Toggle View"),
        Binding("t", "toggle_compact", "Compact"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self._config_path = config_path
        self._config = load_config(config_path)
        self.sub_title = str(config_path)
        self._engine = MidiEngine(self._config, self._on_midi_event)
        self._listen_future: asyncio.Future[MidiEvent] | None = None

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
        yield MappingMonitorPanel(id="mapping-monitor-panel")
        yield CompactMonitorPanel(id="compact-monitor-panel")
        yield Footer()

    # ------------------------------------------------------------------
    # MIDI event callback (called from engine threads)
    # ------------------------------------------------------------------

    def _on_midi_event(self, event: MidiEvent) -> None:
        self.call_from_thread(self._post_midi_event, event)

    def _post_midi_event(self, event: MidiEvent) -> None:
        self.query_one("#monitor-panel", MonitorPanel).log_event(event)
        self.query_one("#mapping-monitor-panel", MappingMonitorPanel).log_event(event)
        self.query_one("#compact-monitor-panel", CompactMonitorPanel).log_event(event)
        if (
            event.direction == "IN"
            and self._listen_future is not None
            and not self._listen_future.done()
        ):
            self._listen_future.set_result(event)
            self._listen_future = None

    def listen_for_event(self) -> asyncio.Future[MidiEvent]:
        """Return a Future that resolves on the next incoming MIDI event."""
        loop = asyncio.get_running_loop()
        self._listen_future = loop.create_future()
        return self._listen_future

    def cancel_listen(self) -> None:
        if self._listen_future is not None and not self._listen_future.done():
            self._listen_future.cancel()
            self._listen_future = None

    # ------------------------------------------------------------------
    # Panel refresh helpers
    # ------------------------------------------------------------------

    def _refresh_panels(self) -> None:
        self.query_one("#device-panel", DevicePanel).refresh_devices(self._config)
        self.query_one("#mapping-panel", MappingPanel).refresh_mappings(self._config)
        self.query_one("#mapping-monitor-panel", MappingMonitorPanel).refresh_rows(self._config)

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

    @on(Button.Pressed, ".del-btn")
    async def _handle_delete_device(self, event: Button.Pressed) -> None:
        row = event.button.parent
        if isinstance(row, DeviceRow):
            name = row._dev_name
            new_devices = {k: v for k, v in self._config.devices.items() if k != name}
            self._update_config(AppConfig(devices=new_devices, mappings=list(self._config.mappings)))

    @on(MappingRow.EditPressed)
    @work
    async def _edit_mapping(self, event: MappingRow.EditPressed) -> None:
        idx = event.idx
        existing = self._config.mappings[idx]
        result: Mapping | None = await self.push_screen_wait(MappingModal(self._config, existing))
        if result is None:
            return
        new_mappings = list(self._config.mappings)
        new_mappings[idx] = result
        self._update_config(AppConfig(devices=dict(self._config.devices), mappings=new_mappings))

    @on(MappingRow.DeletePressed)
    def _delete_mapping(self, event: MappingRow.DeletePressed) -> None:
        idx = event.idx
        new_mappings = [m for i, m in enumerate(self._config.mappings) if i != idx]
        self._update_config(AppConfig(devices=dict(self._config.devices), mappings=new_mappings))

    # ------------------------------------------------------------------
    # Key actions
    # ------------------------------------------------------------------

    def action_save_config(self) -> None:
        save_config(self._config, self._config_path)
        self.notify(f"Saved to {self._config_path}", title="Saved")

    def action_toggle_view(self) -> None:
        monitor = self.query_one("#monitor-panel", MonitorPanel)
        mapping_monitor = self.query_one("#mapping-monitor-panel", MappingMonitorPanel)
        if monitor.display:
            monitor.display = False
            mapping_monitor.display = True
        else:
            monitor.display = True
            mapping_monitor.display = False

    def action_toggle_compact(self) -> None:
        compact = self.query_one("#compact-monitor-panel", CompactMonitorPanel)
        monitor = self.query_one("#monitor-panel")
        mapping_monitor = self.query_one("#mapping-monitor-panel")
        is_compact = compact.display

        if not is_compact:
            # Entering compact: remember which monitor was active
            self._pre_compact_monitor = monitor.display
            self._pre_compact_mapping = mapping_monitor.display
            compact.display = True
            self.query_one(Header).display = False
            self.query_one("#top-row").display = False
            monitor.display = False
            mapping_monitor.display = False
            self.query_one(Footer).display = False
        else:
            # Leaving compact: restore previous state
            compact.display = False
            self.query_one(Header).display = True
            self.query_one("#top-row").display = True
            self.query_one(Footer).display = True
            monitor.display = getattr(self, "_pre_compact_monitor", True)
            mapping_monitor.display = getattr(self, "_pre_compact_mapping", False)

    def action_clear_monitor(self) -> None:
        self.query_one("#monitor-log", RichLog).clear()

    def action_quit(self) -> None:
        self.exit()
