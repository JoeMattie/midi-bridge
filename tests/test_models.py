from midi_bridge.models import AppConfig, DeviceConfig, Mapping


def test_device_config_fields():
    dev = DeviceConfig(name="pad", port="IAC Bus 1", direction="input")
    assert dev.name == "pad"
    assert dev.port == "IAC Bus 1"
    assert dev.direction == "input"


def test_mapping_defaults():
    m = Mapping(name="test", input_device="pad", input_type="program_change", output_device="synth")
    assert m.input_channel == 1
    assert m.input_value == -1
    assert m.output_type == "control_change"
    assert m.output_channel == 1
    assert m.output_control == 0
    assert m.output_value == 127
    assert m.momentary is False
    assert m.momentary_delay_ms == 100


def test_app_config_defaults():
    cfg = AppConfig()
    assert cfg.devices == {}
    assert cfg.mappings == []


def test_app_config_mutable_defaults_are_independent():
    a = AppConfig()
    b = AppConfig()
    a.mappings.append(Mapping(name="x", input_device="a", input_type="note_on", output_device="b"))
    assert b.mappings == []
