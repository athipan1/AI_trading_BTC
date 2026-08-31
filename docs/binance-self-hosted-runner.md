# Binance Spot Testnet self-hosted runner

The Binance Testnet order workflow is intentionally routed only to a self-hosted Linux runner carrying the custom label `binance-testnet`.

## Why

A real smoke test from a GitHub-hosted runner in `eastus` reached `https://testnet.binance.vision` but Binance returned HTTP 451 for a restricted location. The order step was therefore skipped. Do not use a proxy or VPN to bypass Binance eligibility restrictions. Register the runner only on a machine/network where use of Binance Spot Testnet is permitted for the account.

## Runner requirements

- Linux supported by GitHub Actions self-hosted runners
- outbound HTTPS to GitHub and `testnet.binance.vision`
- Python 3.12 available or installable by `actions/setup-python`
- dedicated machine or VM preferred
- custom runner label: `binance-testnet`

## Register the runner

1. In this repository open `Settings → Actions → Runners → New self-hosted runner`.
2. Select Linux and the machine architecture.
3. Run the download and checksum commands GitHub generates. Do not copy a registration token into this repository, an issue, a workflow log, or a shell history you share.
4. When running `config.sh`, add the custom label:

   ```bash
   ./config.sh \
     --url https://github.com/athipan1/AI_trading_BTC \
     --token '<ONE_TIME_TOKEN_FROM_GITHUB>' \
     --labels binance-testnet
   ```

5. Install the runner as a service using the commands shown by GitHub for the selected OS, or run `./run.sh` for a temporary smoke test.

GitHub automatically supplies the default `self-hosted` and OS labels. The workflow additionally requires `linux` and `binance-testnet`.

## Validate network before using credentials

From the runner host:

```bash
curl -i https://testnet.binance.vision/api/v3/time
```

Expected result: HTTP 200 with JSON containing `serverTime`.

If the response is HTTP 451 or otherwise states that service is unavailable for the location, stop. The workflow will fail closed before a signed request or order attempt.

## GitHub repository secrets

These already belong in GitHub Actions secrets, never in files:

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`

## Order workflow

Open `Actions → Binance Spot Testnet Order`.

First run:

- `mode=preflight`
- `side=buy`
- `notional_usdt=10`
- confirmation empty

After preflight succeeds, run:

- `mode=place_order`
- `side=buy`
- `notional_usdt=10`
- `confirmation=BINANCE_TESTNET`

The workflow hard-caps each requested Testnet order at 25 USDT and refuses non-Testnet API hosts.
