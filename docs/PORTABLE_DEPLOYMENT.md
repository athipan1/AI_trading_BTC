# Portable one-command deployment

The project supports two runtime backends through `scripts/btc-stack.sh`:

- Docker Compose for Linux workstations, VPS, and cloud VMs.
- Native Termux + Ubuntu/proot for the existing Android deployment.

The launcher is intentionally thin. It reuses the existing trading entry points and Hermes3D overlay instead of introducing a second execution architecture.

## VPS / Linux

Prerequisites:

- Git
- Docker Engine
- Docker Compose v2 (`docker compose`)

Bootstrap a new host:

```bash
git clone https://github.com/athipan1/AI_trading_BTC.git
cd AI_trading_BTC
cp .env.example .env
```

Edit `.env` and provide separate Spot Testnet and Futures Testnet credentials plus LINE credentials when notifications are required. Never commit `.env`.

Install the short commands:

```bash
bash scripts/install_btc_commands.sh
```

Start the full stack from any directory:

```bash
btc-start
```

The Docker backend starts these services:

- `btc-trader` read-only FastAPI runtime on port 8000
- `spot-auto` Binance Spot Testnet automatic trader
- `futures-short` Binance USD-M Futures Testnet short trader
- `spot-monitor` Spot TP/SL notification monitor
- `hermes3d` read-only 3D office on port 3000

Useful commands:

```bash
btc-status
btc-logs
btc-stop
```

Local endpoints:

- Runtime health: `http://127.0.0.1:8000/health`
- Hermes3D office: `http://127.0.0.1:3000/office`

For remote access, put a TLS reverse proxy or VPN in front of port 3000. Do not expose exchange credentials or raw internal APIs through a public reverse proxy.

## Termux

On the existing Termux installation, the launcher automatically selects the native backend when Docker Compose is unavailable.

It starts the existing native workers, Sidecar, FastAPI runtime, and Hermes3D through Ubuntu/proot. The default Hermes runtime directory inside Ubuntu is:

```text
/root/Hermes3D-runtime
```

Override it when needed:

```bash
export HERMES3D_RUNTIME_DIR=/root/Hermes3D-runtime
```

Install the commands once:

```bash
cd ~/AI_trading_BTC
bash scripts/install_btc_commands.sh
```

Then from any Termux directory:

```bash
btc-start
btc-status
btc-logs
btc-stop
```

The native launcher is idempotent: it checks recorded PIDs and does not intentionally start duplicate workers.

## Explicit backend selection

Automatic backend selection prefers Docker Compose, then Termux.

Override it with:

```bash
BTC_STACK_BACKEND=docker btc-start
```

or:

```bash
BTC_STACK_BACKEND=termux btc-start
```

## State portability

Runtime state remains under the repository `state/` directory. Docker services bind-mount the same directory at `/app/state`, preserving the existing PositionStore, strategy-state, and Hermes3D journal contracts.

Before migrating a live testnet deployment to another host, stop the old stack first and copy `state/` if continuity is required. Do not run two hosts simultaneously with the same exchange credentials and the same strategy identity unless duplicate execution is explicitly intended.
