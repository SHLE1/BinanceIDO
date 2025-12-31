# BSC Method Call Monitor

Polls Binance Smart Chain for calls to a target contract and method ID, then notifies a Telegram chat when matches are found.

## Setup

1) Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2) Configure environment (can be exported or placed in a `.env` you load before running):
   - `BSC_RPC_URL` (optional): HTTPS RPC endpoint. Defaults to `https://bsc-dataseed.binance.org`.
   - `BSC_CONTRACT` (optional): Contract address to watch. Defaults to `0x56a3bF66db83e59d13DFED48205Bb84c33B08d1b`.
   - `BSC_METHOD_ID` (optional): 4-byte method selector (with `0x` prefix). Defaults to `0xfd5c9779`.
   - `POLL_INTERVAL` (optional): Seconds between head checks. Defaults to `3`.
   - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: Required to send notifications.
   - `START_BLOCK` (optional): Start scanning from this historical block number (useful for testing).
   - `EXIT_AFTER_CATCHUP` (optional, default `false`): If `true`, exit once the scanner catches up to chain head.

## Run

```bash
python monitor.py
```

The script starts at the current head block and checks each new block for transactions whose `to` address matches `BSC_CONTRACT` and whose `input` begins with `BSC_METHOD_ID`. When a match is found, a concise message is sent to the configured Telegram chat.
Note: BSC is PoA; the script already injects `geth_poa_middleware` so block parsing succeeds.
