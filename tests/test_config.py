import pytest
from pathlib import Path

from midi_bridge.config import load_config, save_config
from midi_bridge.models import AppConfig, DeviceConfig, Mapping


@pytest.fixture
def tmp_toml(tmp_path):
    return tmp_path / "config.toml"


def test_load_missing_file_returns_empty_config(tmp_toml):
    cfg = load_config(tmp_toml)
    assert cfg.devices == {}
    assert cfg.mappings == []


def test_roundtrip_devices(tmp_toml):
    cfg = AppConfig(
        devices={
            "pad": DeviceConfig(name="pad", port="IAC Bus 1", direction="input"),
            "synth": DeviceConfig(name="synth", port="IAC Bus 2", direction="output"),
        }
    )
    save_config(cfg, tmp_toml)
    loaded = load_config(tmp_toml)

    assert set(loaded.devices.keys()) == {"pad", "synth"}
    assert loaded.devices["pad"].port == "IAC Bus 1"
    assert loaded.devices["pad"].direction == "input"
    assert loaded.devices["synth"].direction == "output"


def test_roundtrip_mapping_all_fields(tmp_toml):
    m = Mapping(
        name="PC5 -> CC64",
        input_device="pad",
        input_type="program_change",
        input_channel=2,
        input_value=5,
        output_device="synth",
        output_type="control_change",
        output_channel=3,
        output_control=64,
        output_value=127,
        momentary=True,
        momentary_delay_ms=200,
    )
    cfg = AppConfig(mappings=[m])
    save_config(cfg, tmp_toml)
    loaded = load_config(tmp_toml)

    assert len(loaded.mappings) == 1
    r = loaded.mappings[0]
    assert r.name == "PC5 -> CC64"
    assert r.input_device == "pad"
    assert r.input_type == "program_change"
    assert r.input_channel == 2
    assert r.input_value == 5
    assert r.output_device == "synth"
    assert r.output_type == "control_change"
    assert r.output_channel == 3
    assert r.output_control == 64
    assert r.output_value == 127
    assert r.momentary is True
    assert r.momentary_delay_ms == 200


def test_roundtrip_multiple_mappings(tmp_toml):
    mappings = [
        Mapping(name=f"map{i}", input_device="pad", input_type="note_on",
                input_value=i, output_device="synth")
        for i in range(3)
    ]
    cfg = AppConfig(mappings=mappings)
    save_config(cfg, tmp_toml)
    loaded = load_config(tmp_toml)

    assert len(loaded.mappings) == 3
    for i, m in enumerate(loaded.mappings):
        assert m.name == f"map{i}"
        assert m.input_value == i


def test_save_empty_config_produces_valid_toml(tmp_toml):
    save_config(AppConfig(), tmp_toml)
    assert tmp_toml.exists()
    loaded = load_config(tmp_toml)
    assert loaded.devices == {}
    assert loaded.mappings == []


def test_input_value_minus_one_roundtrips(tmp_toml):
    m = Mapping(name="any", input_device="pad", input_type="control_change",
                input_value=-1, output_device="synth")
    save_config(AppConfig(mappings=[m]), tmp_toml)
    loaded = load_config(tmp_toml)
    assert loaded.mappings[0].input_value == -1
