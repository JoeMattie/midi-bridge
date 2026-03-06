"""
Textual pilot tests for MidiBridgeApp UI interactions.

MIDI port discovery and engine I/O are mocked throughout so no hardware
is required.  The tests exercise the full widget/screen lifecycle via
Textual's built-in run_test() / Pilot API.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import Button, DataTable, Input, Select, Switch

from midi_bridge.app import DeviceModal, MappingModal, MidiBridgeApp
from midi_bridge.models import AppConfig, DeviceConfig, Mapping

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

FAKE_PORTS = ["IAC Driver Bus 1", "IAC Driver Bus 2"]

_PATCH_IN  = "midi_bridge.app.list_input_ports"
_PATCH_OUT = "midi_bridge.app.list_output_ports"


def _make_app(tmp_path: Path, config: AppConfig | None = None) -> MidiBridgeApp:
    cfg_path = tmp_path / "config.toml"
    if config is not None:
        from midi_bridge.config import save_config
        save_config(config, cfg_path)
    app = MidiBridgeApp(config_path=cfg_path)
    app._engine.start  = MagicMock()   # type: ignore[method-assign]
    app._engine.stop   = MagicMock()   # type: ignore[method-assign]
    app._engine.reload = MagicMock()   # type: ignore[method-assign]
    return app


async def _pause(pilot, n: int = 2) -> None:
    """Pause n times to let async handlers and pending mounts settle."""
    for _ in range(n):
        await pilot.pause()


def _set_input(app, widget_id: str, text: str) -> None:
    """Set an Input widget's value directly (avoids needing pilot.type)."""
    app.query_one(widget_id, Input).value = text


def _preloaded_config() -> AppConfig:
    return AppConfig(
        devices={
            "pad":   DeviceConfig(name="pad",   port=FAKE_PORTS[0], direction="input"),
            "synth": DeviceConfig(name="synth", port=FAKE_PORTS[1], direction="output"),
        },
        mappings=[
            Mapping(
                name="PC5->CC64",
                input_device="pad",
                input_type="program_change",
                input_channel=1,
                input_value=5,
                output_device="synth",
                output_type="control_change",
                output_channel=1,
                output_control=64,
                output_value=127,
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1. App startup
# ---------------------------------------------------------------------------

class TestAppStartup:
    async def test_panels_rendered_on_launch(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                assert app.query_one("#device-panel")
                assert app.query_one("#mapping-panel")
                assert app.query_one("#monitor-panel")

    async def test_add_device_button_visible(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                assert app.query_one("#add-device", Button)

    async def test_add_mapping_button_visible(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                assert app.query_one("#add-mapping", Button)

    async def test_mapping_table_has_correct_columns(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                table = app.query_one("#mapping-table", DataTable)
                col_labels = [str(col.label) for col in table.columns.values()]
                assert "Name" in col_labels
                assert "Input Device" in col_labels
                assert "Output Device" in col_labels

    async def test_preloaded_config_shows_mapping_rows(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                table = app.query_one("#mapping-table", DataTable)
                assert table.row_count == 1

    async def test_engine_started_on_mount(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                app._engine.start.assert_called_once()

    async def test_engine_stopped_on_unmount(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                pass
        app._engine.stop.assert_called_once()


# ---------------------------------------------------------------------------
# 2. DeviceModal — open & cancel
# ---------------------------------------------------------------------------

class TestDeviceModalOpenCancel:
    async def test_clicking_add_device_opens_modal(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                assert isinstance(app.screen, DeviceModal)

    async def test_cancel_closes_modal_without_adding_device(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                await pilot.click("#cancel")
                await _pause(pilot)
                assert not isinstance(app.screen, DeviceModal)
                assert app._config.devices == {}

    async def test_modal_shows_available_ports(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, DeviceModal)
                port_select = modal.query_one("#dev-port", Select)
                # _options is list of (prompt, value) tuples
                option_values = [opt[1] for opt in port_select._options]
                assert FAKE_PORTS[0] in option_values
                assert FAKE_PORTS[1] in option_values

    async def test_modal_name_input_starts_empty(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, DeviceModal)
                assert modal.query_one("#dev-name", Input).value == ""


# ---------------------------------------------------------------------------
# 3. DeviceModal — validation
# ---------------------------------------------------------------------------

class TestDeviceModalValidation:
    async def test_ok_with_empty_name_keeps_modal_open(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, DeviceModal)
                # Set a valid port (auto-fills name), then explicitly clear the name
                modal.query_one("#dev-port", Select).value = FAKE_PORTS[0]
                await _pause(pilot)
                modal.query_one("#dev-name", Input).value = ""
                await pilot.click("#ok")
                await _pause(pilot)
                assert isinstance(app.screen, DeviceModal)
                assert app._config.devices == {}

    async def test_ok_with_blank_port_keeps_modal_open(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, DeviceModal)
                # Type a name but leave port at NULL (blank)
                modal.query_one("#dev-name", Input).value = "mydevice"
                await pilot.click("#ok")
                await _pause(pilot)
                assert isinstance(app.screen, DeviceModal)
                assert app._config.devices == {}


# ---------------------------------------------------------------------------
# 4. DeviceModal — successful submission
# ---------------------------------------------------------------------------

class TestDeviceModalSubmit:
    async def test_valid_submission_adds_device_to_config(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, DeviceModal)

                modal.query_one("#dev-name", Input).value = "mypad"
                modal.query_one("#dev-port", Select).value = FAKE_PORTS[0]

                await pilot.click("#ok")
                await _pause(pilot)

                assert not isinstance(app.screen, DeviceModal)
                assert "mypad" in app._config.devices
                assert app._config.devices["mypad"].port == FAKE_PORTS[0]

    async def test_submitted_device_direction_default_is_input(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, DeviceModal)

                modal.query_one("#dev-name", Input).value = "mypad"
                modal.query_one("#dev-port", Select).value = FAKE_PORTS[0]
                await pilot.click("#ok")
                await _pause(pilot)

                assert app._config.devices["mypad"].direction == "input"

    async def test_submitted_device_appears_in_device_panel(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, DeviceModal)

                modal.query_one("#dev-name", Input).value = "mypad"
                modal.query_one("#dev-port", Select).value = FAKE_PORTS[0]
                await pilot.click("#ok")
                await _pause(pilot, n=3)  # extra time for DeviceRow to mount

                assert app.query_one("#del-dev-mypad", Button)

    async def test_adding_device_triggers_engine_reload(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-device")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, DeviceModal)

                modal.query_one("#dev-name", Input).value = "mypad"
                modal.query_one("#dev-port", Select).value = FAKE_PORTS[0]
                await pilot.click("#ok")
                await _pause(pilot)

                app._engine.reload.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Device deletion
# ---------------------------------------------------------------------------

class TestDeviceDeletion:
    async def test_delete_button_removes_device(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                assert "pad" in app._config.devices
                await _pause(pilot)  # let DeviceRow layout settle after mount
                await pilot.click("#del-dev-pad")
                await _pause(pilot)
                assert "pad" not in app._config.devices

    async def test_delete_device_triggers_engine_reload(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await _pause(pilot)  # let DeviceRow layout settle after mount
                await pilot.click("#del-dev-pad")
                await _pause(pilot)
                app._engine.reload.assert_called()

    async def test_remaining_device_still_present_after_delete(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await _pause(pilot)  # let DeviceRow layout settle after mount
                await pilot.click("#del-dev-pad")
                await _pause(pilot)
                assert "synth" in app._config.devices


# ---------------------------------------------------------------------------
# 6. MappingModal — open & cancel
# ---------------------------------------------------------------------------

class TestMappingModalOpenCancel:
    async def test_clicking_add_mapping_opens_modal(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                assert isinstance(app.screen, MappingModal)

    async def test_cancel_closes_mapping_modal(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                await pilot.click("#cancel")
                await _pause(pilot)
                assert not isinstance(app.screen, MappingModal)
                assert app._config.mappings == []

    async def test_mapping_modal_defaults(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, MappingModal)

                assert modal.query_one("#map-name", Input).value == ""
                assert modal.query_one("#map-in-ch", Input).value == "1"
                assert modal.query_one("#map-in-val", Input).value == "-1"
                assert modal.query_one("#map-out-ch", Input).value == "1"
                assert modal.query_one("#map-out-val", Input).value == "127"
                assert modal.query_one("#map-momentary", Switch).value is False


# ---------------------------------------------------------------------------
# 7. MappingModal — successful submission
# ---------------------------------------------------------------------------

class TestMappingModalSubmit:
    async def test_valid_submission_adds_mapping(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, MappingModal)

                modal.query_one("#map-name", Input).value = "My Mapping"
                modal.query_one("#map-in-device", Select).value = "pad"
                modal.query_one("#map-out-device", Select).value = "synth"

                await pilot.click("#ok")
                await _pause(pilot)

                assert not isinstance(app.screen, MappingModal)
                assert len(app._config.mappings) == 2
                new_m = app._config.mappings[-1]
                assert new_m.name == "My Mapping"
                assert new_m.input_device == "pad"
                assert new_m.output_device == "synth"

    async def test_submitted_mapping_appears_in_table(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, MappingModal)

                modal.query_one("#map-name", Input).value = "TableTest"
                modal.query_one("#map-in-device", Select).value = "pad"
                modal.query_one("#map-out-device", Select).value = "synth"

                await pilot.click("#ok")
                await _pause(pilot)

                table = app.query_one("#mapping-table", DataTable)
                assert table.row_count == 2

    async def test_adding_mapping_triggers_engine_reload(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, MappingModal)

                modal.query_one("#map-name", Input).value = "Reload Test"
                modal.query_one("#map-in-device", Select).value = "pad"
                modal.query_one("#map-out-device", Select).value = "synth"

                await pilot.click("#ok")
                await _pause(pilot)

                app._engine.reload.assert_called()

    async def test_momentary_fields_preserved_after_submit(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, MappingModal)

                modal.query_one("#map-name", Input).value = "Momentary Test"
                modal.query_one("#map-in-device", Select).value = "pad"
                modal.query_one("#map-out-device", Select).value = "synth"

                # Toggle momentary on and set delay directly
                modal.query_one("#map-momentary", Switch).value = True
                modal.query_one("#map-delay", Input).value = "250"

                await pilot.click("#ok")
                await _pause(pilot)

                new_m = app._config.mappings[-1]
                assert new_m.momentary is True
                assert new_m.momentary_delay_ms == 250


# ---------------------------------------------------------------------------
# 8. Momentary section toggle
# ---------------------------------------------------------------------------

class TestMomentaryToggle:
    async def test_momentary_section_hidden_by_default(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, MappingModal)

                section = modal.query_one("#momentary-section")
                assert "visible" not in section.classes

    async def test_toggling_momentary_switch_shows_section(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, MappingModal)

                # Set value directly — avoids out-of-viewport click issues
                modal.query_one("#map-momentary", Switch).value = True
                await _pause(pilot)

                section = modal.query_one("#momentary-section")
                assert "visible" in section.classes

    async def test_toggling_momentary_switch_twice_hides_section(self, tmp_path):
        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.click("#add-mapping")
                await _pause(pilot)
                modal = app.screen
                assert isinstance(modal, MappingModal)

                switch = modal.query_one("#map-momentary", Switch)
                switch.value = True
                await _pause(pilot)
                switch.value = False
                await _pause(pilot)

                section = modal.query_one("#momentary-section")
                assert "visible" not in section.classes

    async def test_editing_momentary_mapping_shows_section_open(self, tmp_path):
        """When editing an existing momentary mapping the section should start visible."""
        m = Mapping(
            name="mom", input_device="pad", input_type="program_change",
            output_device="synth", momentary=True, momentary_delay_ms=150,
        )
        app = _make_app(tmp_path, config=AppConfig(
            devices={
                "pad":   DeviceConfig(name="pad",   port=FAKE_PORTS[0], direction="input"),
                "synth": DeviceConfig(name="synth", port=FAKE_PORTS[1], direction="output"),
            },
            mappings=[m],
        ))
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                table = app.query_one("#mapping-table", DataTable)
                await pilot.click("#mapping-table")
                table.move_cursor(row=0, column=4)
                await pilot.press("enter")
                await _pause(pilot)

                modal = app.screen
                assert isinstance(modal, MappingModal)
                section = modal.query_one("#momentary-section")
                assert "visible" in section.classes


# ---------------------------------------------------------------------------
# 9. Mapping edit via DataTable
# ---------------------------------------------------------------------------

class TestMappingEdit:
    async def test_clicking_edit_column_opens_mapping_modal(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                table = app.query_one("#mapping-table", DataTable)
                await pilot.click("#mapping-table")
                table.move_cursor(row=0, column=4)
                await pilot.press("enter")
                await _pause(pilot)
                assert isinstance(app.screen, MappingModal)

    async def test_edit_modal_prefilled_with_existing_values(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                table = app.query_one("#mapping-table", DataTable)
                await pilot.click("#mapping-table")
                table.move_cursor(row=0, column=4)
                await pilot.press("enter")
                await _pause(pilot)

                modal = app.screen
                assert isinstance(modal, MappingModal)
                assert modal.query_one("#map-name", Input).value == "PC5->CC64"
                assert modal.query_one("#map-in-ch", Input).value == "1"
                assert modal.query_one("#map-in-val", Input).value == "5"

    async def test_edit_cancel_leaves_mapping_unchanged(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                table = app.query_one("#mapping-table", DataTable)
                await pilot.click("#mapping-table")
                table.move_cursor(row=0, column=4)
                await pilot.press("enter")
                await _pause(pilot)

                await pilot.click("#cancel")
                await _pause(pilot)
                assert app._config.mappings[0].name == "PC5->CC64"

    async def test_edit_submit_updates_mapping(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                table = app.query_one("#mapping-table", DataTable)
                await pilot.click("#mapping-table")
                table.move_cursor(row=0, column=4)
                await pilot.press("enter")
                await _pause(pilot)

                modal = app.screen
                assert isinstance(modal, MappingModal)
                modal.query_one("#map-name", Input).value = "Renamed"

                await pilot.click("#ok")
                await _pause(pilot)

                assert app._config.mappings[0].name == "Renamed"
                assert len(app._config.mappings) == 1  # no duplicate


# ---------------------------------------------------------------------------
# 10. Mapping deletion via DataTable
# ---------------------------------------------------------------------------

class TestMappingDeletion:
    async def test_clicking_del_column_removes_mapping(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                table = app.query_one("#mapping-table", DataTable)
                await pilot.click("#mapping-table")
                table.move_cursor(row=0, column=5)
                await pilot.press("enter")
                await _pause(pilot)

                assert app._config.mappings == []
                assert table.row_count == 0

    async def test_delete_triggers_engine_reload(self, tmp_path):
        app = _make_app(tmp_path, config=_preloaded_config())
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                table = app.query_one("#mapping-table", DataTable)
                await pilot.click("#mapping-table")
                table.move_cursor(row=0, column=5)
                await pilot.press("enter")
                await _pause(pilot)
                app._engine.reload.assert_called()


# ---------------------------------------------------------------------------
# 11. Save config (S key)
# ---------------------------------------------------------------------------

class TestSaveConfig:
    async def test_pressing_s_writes_config_file(self, tmp_path):
        cfg_path = tmp_path / "config.toml"
        app = MidiBridgeApp(config_path=cfg_path)
        app._engine.start  = MagicMock()  # type: ignore[method-assign]
        app._engine.stop   = MagicMock()  # type: ignore[method-assign]
        app._engine.reload = MagicMock()  # type: ignore[method-assign]
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.press("s")
                await _pause(pilot)
        assert cfg_path.exists()

    async def test_saved_file_can_be_reloaded(self, tmp_path):
        from midi_bridge.config import load_config
        cfg = _preloaded_config()
        cfg_path = tmp_path / "config.toml"
        app = _make_app(tmp_path, config=cfg)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                await pilot.press("s")
                await _pause(pilot)
        reloaded = load_config(cfg_path)
        assert "pad" in reloaded.devices
        assert len(reloaded.mappings) == 1
        assert reloaded.mappings[0].name == "PC5->CC64"


# ---------------------------------------------------------------------------
# 12. Monitor panel
# ---------------------------------------------------------------------------

class TestMonitorPanel:
    async def test_midi_event_logged_to_monitor(self, tmp_path):
        import mido
        import time
        from midi_bridge.engine import MidiEvent
        from midi_bridge.app import MonitorPanel
        from textual.widgets import RichLog

        app = _make_app(tmp_path)
        with patch(_PATCH_IN, return_value=FAKE_PORTS), patch(_PATCH_OUT, return_value=FAKE_PORTS):
            async with app.run_test() as pilot:
                event = MidiEvent(
                    timestamp=time.time(),
                    direction="IN",
                    device_name="pad",
                    message=mido.Message("program_change", channel=0, program=5),
                    matched=True,
                )
                monitor = app.query_one("#monitor-panel", MonitorPanel)
                monitor.log_event(event)
                await _pause(pilot)
                log = app.query_one("#monitor-log", RichLog)
                assert log is not None
