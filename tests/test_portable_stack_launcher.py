from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/btc-stack.sh"
INSTALLER = ROOT / "scripts/install_btc_commands.sh"
RUNTIME_COMPOSE = ROOT / "docker-compose.runtime.yml"
HERMES_COMPOSE = ROOT / "docker-compose.hermes3d.yml"
HERMES_DOCKERFILE = ROOT / "deploy/hermes3d/Dockerfile"
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


def test_native_python_services_use_unbuffered_output_for_runtime_logs() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    body = source.split("start_native() {", 1)[1].split("\n}\n\ntermux_start_research_scheduler", 1)[0]

    assert "export PYTHONUNBUFFERED=1" in body
    assert '> "$LOG_DIR/$name.log" 2>&1 &' in body


def test_termux_hermes_tracks_the_real_node_server_pid() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "hermes3d_node_pid" in source
    assert "refresh_hermes3d_pid" in source
    assert "pgrep -f '^node server/index.js$'" in source
    assert 'printf \'%s\\n\' "$pid" > "$PID_DIR/hermes3d-office.pid"' in source
    assert "failed to discover node server PID" in source
    assert "termux_stop_hermes" in source
    assert "pkill -f '^node server/index.js$'" in source


def test_phase4631_detects_termux_proot_guest_and_avoids_nested_login() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "is_termux_proot_guest" in source
    assert "hermes_guest_exec" in source
    assert "[[ -x /usr/bin/bash ]]" in source
    assert "^ID=(ubuntu|debian)$" in source
    assert "/data/data/com.termux/files/usr" in source
    assert 'if is_termux_proot_guest; then\n    bash -lc "$guest_command"' in source
    assert 'elif is_termux || is_termux_proot_guest; then' in source


def test_phase4631_routes_office_guest_operations_through_context_helper() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert 'hermes_guest_exec "pgrep -f \'^node server/index.js$\'' in source
    assert 'hermes_guest_exec "pkill -f \'^node server/index.js$\'' in source

    for function_name in (
        "termux_prepare_hermes_staging",
        "termux_swap_hermes_runtime",
        "termux_restore_hermes_runtime",
        "termux_cleanup_hermes_backup",
    ):
        body = source.split(f"{function_name}() {{", 1)[1].split("\n}\n", 1)[0]
        assert "hermes_guest_exec" in body
        assert "proot-distro login ubuntu" not in body


def test_phase4631_start_uses_direct_bash_inside_existing_guest() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    body = source.split("termux_start_hermes() {", 1)[1].split("\n}\n\ntermux_stop_hermes", 1)[0]

    assert "if is_termux_proot_guest; then" in body
    assert 'nohup bash -lc "$start_command"' in body
    assert 'nohup proot-distro login ubuntu -- bash -lc "$start_command"' in body


def test_phase463_office_commands_are_installed_and_dispatched() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")

    commands = (
        "btc-office-start",
        "btc-office-stop",
        "btc-office-restart",
        "btc-office-status",
        "btc-office-rebuild",
    )
    for command in commands:
        assert command in launcher
        assert command in installer

    assert "termux:office-start" in launcher
    assert "termux:office-stop" in launcher
    assert "termux:office-restart" in launcher
    assert "termux:office-status" in launcher
    assert "termux:office-rebuild" in launcher


def test_phase463_rebuild_uses_staging_healthcheck_and_rollback() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert 'staging_dir="${HERMES3D_RUNTIME_DIR}.next"' in source
    assert 'backup_dir="${HERMES3D_RUNTIME_DIR}.previous"' in source
    assert "termux_prepare_hermes_staging" in source
    assert "termux_swap_hermes_runtime" in source
    assert "termux_restore_hermes_runtime" in source
    assert "Hermes3D health check failed; restoring previous runtime." in source
    assert "http://127.0.0.1:3000/office" in source
    assert "cp -a '$REPO_ROOT/deploy/hermes3d/overlay/.'" in source
    assert "npm ci" in source
    assert "npm run build" in source


def test_phase463_termux_rebuild_does_not_restart_trading_processes() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    rebuild = source.split("termux_office_rebuild() {", 1)[1].split("\n}\n\ntermux_start()", 1)[0]

    for trading_process in (
        "spot-auto",
        "futures-short",
        "spot-monitor",
        "hermes3d-sidecar",
        "trading-runtime",
        "phase562-scheduler",
    ):
        assert trading_process not in rebuild


def test_phase463_termux_ref_matches_pinned_docker_ref() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8")
    dockerfile = HERMES_DOCKERFILE.read_text(encoding="utf-8")
    pinned_ref = dockerfile.split("ARG HERMES3D_REF=", 1)[1].splitlines()[0].strip()

    assert f'HERMES3D_REF="${{HERMES3D_REF:-{pinned_ref}}}"' in launcher


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


def test_futures_short_startup_notification_failure_is_fail_soft() -> None:
    source = (ROOT / "scripts/run_binance_futures_testnet_short.py").read_text(encoding="utf-8")
    startup = source.split("if trader.notifier is not None:", 1)[1].split("\n\n    while True:", 1)[0]

    assert "try:" in startup
    assert "except Exception as exc:" in startup
    assert '"event": "NOTIFICATION_WARNING"' in startup
    assert '"notification": "startup"' in startup
