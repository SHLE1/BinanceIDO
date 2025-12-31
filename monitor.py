import os
import time
import logging
from typing import Optional

import requests
from web3 import Web3
from web3.exceptions import BlockNotFound


CONTRACT_ADDRESS = os.getenv("BSC_CONTRACT", "0x56a3bF66db83e59d13DFED48205Bb84c33B08d1b").lower()
METHOD_ID = os.getenv("BSC_METHOD_ID", "0xfd5c9779").lower()
BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "3.0"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def send_telegram(text: str) -> None:
    """Send a Telegram message if credentials are configured."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set; skipping notification")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    if not resp.ok:
        logger.warning("Failed to send Telegram message: %s", resp.text)


def describe_tx(w3: Web3, block_number: int, tx) -> str:
    """Create a concise message for Telegram."""
    value_bnb = w3.from_wei(tx["value"], "ether")
    hash_hex = tx["hash"].hex()
    sender = tx["from"]
    to = tx["to"]
    return (
        f"BSC call match\n"
        f"Block: {block_number}\n"
        f"Tx: {hash_hex}\n"
        f"From: {sender}\n"
        f"To: {to}\n"
        f"Value: {value_bnb} BNB\n"
        f"MethodID: {METHOD_ID}"
    )


def process_block(w3: Web3, block_number: int) -> None:
    """Load a block and notify on matching transactions."""
    try:
        block = w3.eth.get_block(block_number, full_transactions=True)
    except BlockNotFound:
        logger.warning("Block %s not found yet; will retry", block_number)
        return

    txs = block.get("transactions", [])
    for tx in txs:
        to_addr = tx.get("to")
        input_data: Optional[str] = tx.get("input")
        if not to_addr or not input_data:
            continue

        if to_addr.lower() != CONTRACT_ADDRESS:
            continue

        if not input_data.lower().startswith(METHOD_ID):
            continue

        message = describe_tx(w3, block_number, tx)
        logger.info("Match found in block %s tx %s", block_number, tx["hash"].hex())
        send_telegram(message)


def main() -> None:
    w3 = Web3(Web3.HTTPProvider(BSC_RPC_URL, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        raise RuntimeError(f"Cannot connect to BSC RPC at {BSC_RPC_URL}")

    latest = w3.eth.block_number
    logger.info("Connected to BSC RPC. Starting from block %s", latest)

    while True:
        try:
            head = w3.eth.block_number
            if head > latest:
                for block_number in range(latest + 1, head + 1):
                    process_block(w3, block_number)
                latest = head
            time.sleep(POLL_INTERVAL)
        except Exception:
            logger.exception("Error while polling; retrying soon")
            time.sleep(5)


if __name__ == "__main__":
    main()
