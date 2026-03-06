import tomllib
import tomli_w
from pathlib import Path

from .models import AppConfig, DeviceConfig, Mapping


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        return AppConfig()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    devices: dict[str, DeviceConfig] = {}
    for name, dev in data.get("devices", {}).items():
        devices[name] = DeviceConfig(
            name=name,
            port=dev["port"],
            direction=dev["direction"],
        )

    mappings: list[Mapping] = []
    for m in data.get("mappings", []):
        mappings.append(Mapping(
            name=m.get("name", ""),
            input_device=m.get("input_device", ""),
            input_type=m.get("input_type", "program_change"),
            input_channel=m.get("input_channel", 1),
            input_value=m.get("input_value", -1),
            output_device=m.get("output_device", ""),
            output_type=m.get("output_type", "control_change"),
            output_channel=m.get("output_channel", 1),
            output_control=m.get("output_control", 0),
            output_value=m.get("output_value", 127),
            momentary=m.get("momentary", False),
            momentary_delay_ms=m.get("momentary_delay_ms", 100),
        ))

    return AppConfig(devices=devices, mappings=mappings)


def save_config(config: AppConfig, path: Path) -> None:
    data: dict = {}

    if config.devices:
        data["devices"] = {
            name: {"port": dev.port, "direction": dev.direction}
            for name, dev in config.devices.items()
        }

    if config.mappings:
        data["mappings"] = [
            {
                "name": m.name,
                "input_device": m.input_device,
                "input_type": m.input_type,
                "input_channel": m.input_channel,
                "input_value": m.input_value,
                "output_device": m.output_device,
                "output_type": m.output_type,
                "output_channel": m.output_channel,
                "output_control": m.output_control,
                "output_value": m.output_value,
                "momentary": m.momentary,
                "momentary_delay_ms": m.momentary_delay_ms,
            }
            for m in config.mappings
        ]

    with open(path, "wb") as f:
        tomli_w.dump(data, f)
