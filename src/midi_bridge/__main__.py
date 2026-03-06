import argparse
from pathlib import Path

from .app import MidiBridgeApp


def main() -> None:
    parser = argparse.ArgumentParser(description="MIDI Bridge — route and transform MIDI messages")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to config file (default: ./config.toml)",
    )
    args = parser.parse_args()

    app = MidiBridgeApp(config_path=args.config)
    app.run()


if __name__ == "__main__":
    main()
