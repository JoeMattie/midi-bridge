.PHONY: run help

CONFIG ?= config.toml

help:
	@echo "Usage:"
	@echo "  make run [CONFIG=path/to/config.toml]"
	@echo ""
	@echo "Options:"
	@echo "  CONFIG   Path to config file (default: config.toml)"

run:
	uv run midi-bridge --config $(CONFIG)
