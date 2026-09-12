from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/btc-stack.sh"
INSTALLER = ROOT / "scripts/install_btc_commands.sh"
RUNTIME_COMPOSE = ROOT / "docker-compose.runtime.yml"
HERMES_COMPOSE = ROOT / "docker-compose.hermes3d.yml"
ENV_EXAMPLE = ROOT / ".env.example"


def test_runtime_compose_reuses_existing_execution_entrypoints() -> None:
    source = RUNTIME_COMPOSE.read_text(encoding="utf-8")

    assert "scripts/run_binance_testnet_auto.py" in source
    assert "BINANCE_TESTNET_AUTO" in source
    assert "scripts/run_binance_futures_testnet_short.py" in source
    assert "BINANCE_FUTURES_TESTNET_SHORT" in source
    assert "scripts/monitor_binance_testnet_positions.py" in source
    assert "./state:/app/state" in source


def test_launcher_supports_docker_and_termux_without_embedding_secrets() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "docker compose" in source
    assert "proot-distro" in source
    assert "BTC_STACK_BACKEND" in source
    assert "BINANCE_TESTNET_API_KEY" in source
    assert "BINANCE_FUTURES_TESTNET_API_KEY" in source
    assert "api_secret=" not in source.lower()
    assert "create_order" not in source.lower()


def test_launcher_is_idempotent_for_native_processes() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "pid_alive" in source
    assert "already running" in source
    assert "runtime/pids" not in source or "PID_DIR" in source


def test_installer_exposes_commands_from_any_directory() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    for command in ("btc-start", "btc-stop", "btc-status", "btc-logs"):
        assert command in source
    assert "/usr/local/bin" in source
    assert "PREFIX" in source


def test_compose_keeps_hermes_read_only_gateway_contract() -> None:
    source = HERMES_COMPOSE.read_text(encoding="utf-8")

    assert "AI_TRADING_RUNTIME_URL: http://btc-trader:8000" in source
    assert "HERMES3D_GATEWAY_ADAPTER_TYPE: custom" in source
    assert "CUSTOM_RUNTIME_ALLOWLIST: btc-trader" in source


def test_example_env_supports_portable_spot_and_futures_stack() -> None:
    source = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "BTC_TESTNET_AUTO_CANDLE_LIMIT=240" in source
    assert "BINANCE_FUTURES_TESTNET_API_KEY=" in source
    assert "BINANCE_FUTURES_TESTNET_API_SECRET=" in source
    assert "BTC_FUTURES_SHORT_CANDLE_LIMIT=240" in source
