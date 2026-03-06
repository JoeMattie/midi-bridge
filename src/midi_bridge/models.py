from dataclasses import dataclass, field
from typing import Literal


MessageType = Literal["program_change", "control_change", "note_on", "note_off", "sysex"]
Direction = Literal["input", "output"]
ValueMode = Literal["fixed", "passthrough"]


@dataclass
class DeviceConfig:
    name: str
    port: str
    direction: Direction


@dataclass
class Mapping:
    name: str
    input_device: str
    input_type: MessageType
    input_channel: int = 1
    input_value: int = -1          # program/CC/note number; -1 = any
    output_device: str = ""
    output_type: MessageType = "control_change"
    output_channel: int = 1
    output_control: int = 0        # CC number for CC output
    output_value: int = 127
    output_value_mode: ValueMode = "fixed"
    momentary: bool = False
    momentary_delay_ms: int = 100


@dataclass
class AppConfig:
    devices: dict[str, DeviceConfig] = field(default_factory=dict)
    mappings: list[Mapping] = field(default_factory=list)
