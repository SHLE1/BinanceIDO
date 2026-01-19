import json
import os
import time
import logging
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
import requests
from web3 import Web3
from web3.exceptions import BlockNotFound
from web3.middleware import geth_poa_middleware


# Load environment variables from a local .env file if present
load_dotenv()

def is_hex(value: str) -> bool:
    return all(char in "0123456789abcdef" for char in value)


def normalize_address(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if not cleaned.startswith("0x"):
        cleaned = f"0x{cleaned}"
    if len(cleaned) != 42 or not is_hex(cleaned[2:]):
        return None
    return cleaned


def normalize_method_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if not cleaned.startswith("0x"):
        cleaned = f"0x{cleaned}"
    if len(cleaned) != 10 or not is_hex(cleaned[2:]):
        return None
    return cleaned


RULES_FILE = os.getenv("BSC_RULES_FILE", "config/monitor_rules.json")

BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "3.0"))
START_BLOCK = os.getenv("START_BLOCK")
EXIT_AFTER_CATCHUP = os.getenv("EXIT_AFTER_CATCHUP", "false").lower() in {"1", "true", "yes"}
LOG_PROGRESS_INTERVAL = float(os.getenv("LOG_PROGRESS_INTERVAL", "60.0"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def normalize_input_hex(input_data: Optional[str]) -> str:
    if input_data is None:
        return ""
    if hasattr(input_data, "hex"):
        value = input_data.hex()
    else:
        value = str(input_data)
    if not value:
        return ""
    value = value.lower()
    if not value.startswith("0x"):
        value = f"0x{value}"
    return value


def extract_method_id(input_hex: str) -> str:
    if not input_hex or input_hex == "0x":
        return ""
    if not input_hex.startswith("0x"):
        input_hex = f"0x{input_hex}"
    return input_hex[:10].lower()


def load_rules_file(path: Path) -> dict:
    rules = {"to_rules": [], "from_rules": []}
    if not path.exists():
        return rules
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        logger.warning("Failed to read rules file %s: %s", path, exc)
        return rules
    if not isinstance(data, dict):
        logger.warning("Rules file %s is not a JSON object", path)
        return rules
    to_rules = data.get("to_rules", [])
    from_rules = data.get("from_rules", [])
    rules["to_rules"] = to_rules if isinstance(to_rules, list) else []
    rules["from_rules"] = from_rules if isinstance(from_rules, list) else []
    return rules


def normalize_rule_list(items: list, address_key: str) -> List[dict]:
    normalized: List[dict] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            logger.warning("Invalid %s rule at index %s: expected object", address_key, index)
            continue
        address = normalize_address(item.get(address_key))
        method_id = normalize_method_id(item.get("method_id"))
        if not address or not method_id:
            logger.warning(
                "Invalid %s rule at index %s: address=%s method_id=%s",
                address_key,
                index,
                item.get(address_key),
                item.get("method_id"),
            )
            continue
        label = item.get("label")
        if isinstance(label, str):
            label = label.strip()
        else:
            label = None
        rule = {address_key: address, "method_id": method_id}
        if label:
            rule["label"] = label
        normalized.append(rule)
    return normalized


def build_active_rules(path: Path) -> dict:
    raw_rules = load_rules_file(path)
    to_rules = normalize_rule_list(raw_rules.get("to_rules", []), "to")
    from_rules = normalize_rule_list(raw_rules.get("from_rules", []), "from")

    rules = {"to_rules": [], "from_rules": []}
    seen_to = set()
    seen_from = set()

    def add_to_rule(address: str, method_id: str, label: Optional[str] = None) -> None:
        key = (address, method_id)
        if key in seen_to:
            return
        seen_to.add(key)
        entry = {"to": address, "method_id": method_id}
        if label:
            entry["label"] = label
        rules["to_rules"].append(entry)

    def add_from_rule(address: str, method_id: str, label: Optional[str] = None) -> None:
        key = (address, method_id)
        if key in seen_from:
            return
        seen_from.add(key)
        entry = {"from": address, "method_id": method_id}
        if label:
            entry["label"] = label
        rules["from_rules"].append(entry)

    for rule in to_rules:
        add_to_rule(rule["to"], rule["method_id"], rule.get("label"))
    for rule in from_rules:
        add_from_rule(rule["from"], rule["method_id"], rule.get("label"))

    return rules


def send_telegram(text: str) -> None:
    """Send a Telegram message if credentials are configured."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set; skipping notification")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})
    if not resp.ok:
        logger.warning("Failed to send Telegram message: %s", resp.text)


def format_match_reasons(match_reasons: List[dict]) -> str:
    parts = []
    for reason in match_reasons:
        kind = reason.get("kind")
        label = reason.get("label")
        if not kind:
            continue
        if label:
            parts.append(f"{kind} ({label})")
        else:
            parts.append(kind)
    return ", ".join(parts) if parts else "n/a"


def describe_tx(w3: Web3, block_number: int, tx, method_id: str, match_reasons: List[dict]) -> str:
    """Create a concise message for Telegram."""
    value_bnb = w3.from_wei(tx["value"], "ether")
    hash_hex = tx["hash"].hex()
    sender = tx["from"]
    to = tx["to"]
    bscscan_link = f"https://bscscan.com/tx/{hash_hex}"
    match_label = format_match_reasons(match_reasons)
    method_display = method_id or "n/a"
    return (
        f"🔔 BSC 监控命中\n"
        f"规则: {match_label}\n"
        f"区块: {block_number}\n"
        f"交易: `{hash_hex}`\n"
        f"链接: {bscscan_link}\n"
        f"From: {sender}\n"
        f"To: {to}\n"
        f"Method: {method_display}\n"
        f"Value: {value_bnb} BNB"
    )


def build_match_reason(kind: str, rule: dict) -> dict:
    label = rule.get("label")
    return {"kind": kind, "label": label}


def process_block(w3: Web3, block_number: int, rules: dict) -> None:
    """Load a block and notify on matching transactions."""
    try:
        block = w3.eth.get_block(block_number, full_transactions=True)
    except BlockNotFound:
        logger.warning("Block %s not found yet; will retry", block_number)
        return

    to_rules = rules.get("to_rules", [])
    from_rules = rules.get("from_rules", [])
    if not to_rules and not from_rules:
        return

    txs = block.get("transactions", [])
    for tx in txs:
        to_addr = tx.get("to")
        input_data: Optional[str] = tx.get("input")
        if not input_data:
            continue

        input_hex = normalize_input_hex(input_data)
        if not input_hex or input_hex == "0x":
            continue
        method_id = extract_method_id(input_hex)

        match_reasons: List[dict] = []
        if to_addr:
            to_addr_lower = to_addr.lower()
            for rule in to_rules:
                if to_addr_lower == rule["to"] and method_id == rule["method_id"]:
                    match_reasons.append(build_match_reason("to+method", rule))

        from_addr = tx.get("from")
        if from_addr:
            from_addr_lower = from_addr.lower()
            for rule in from_rules:
                if from_addr_lower == rule["from"] and method_id == rule["method_id"]:
                    match_reasons.append(build_match_reason("from+method", rule))

        if not match_reasons:
            continue

        message = describe_tx(w3, block_number, tx, method_id, match_reasons)
        logger.info(
            "Match found in block %s tx %s (%s)",
            block_number,
            tx["hash"].hex(),
            format_match_reasons(match_reasons),
        )
        send_telegram(message)


def main() -> None:
    w3 = Web3(Web3.HTTPProvider(BSC_RPC_URL, request_kwargs={"timeout": 20}))
    # BSC uses a PoA consensus; inject middleware so block extraData is accepted.
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    if not w3.is_connected():
        raise RuntimeError(f"Cannot connect to BSC RPC at {BSC_RPC_URL}")

    head_now = w3.eth.block_number
    if START_BLOCK is not None:
        latest = int(START_BLOCK)
        if latest > head_now:
            raise ValueError(f"START_BLOCK {latest} is ahead of chain head {head_now}")
        logger.info("Connected to BSC RPC. Starting from block %s (override)", latest)
    else:
        latest = head_now
        logger.info("Connected to BSC RPC. Starting from block %s", latest)

    last_progress_log = time.time()
    blocks_processed_since_log = 0
    rules_path = Path(RULES_FILE)

    while True:
        try:
            rules = build_active_rules(rules_path)
            head = w3.eth.block_number
            if head > latest:
                for block_number in range(latest + 1, head + 1):
                    process_block(w3, block_number, rules)
                    blocks_processed_since_log += 1
                latest = head
                if EXIT_AFTER_CATCHUP and head == latest:
                    logger.info("Reached chain head; EXIT_AFTER_CATCHUP enabled, exiting")
                    break
            now = time.time()
            if LOG_PROGRESS_INTERVAL > 0 and now - last_progress_log >= LOG_PROGRESS_INTERVAL:
                logger.info(
                    "Progress: last processed=%s, chain head=%s, blocks since last log=%s (watching to_rules=%s, from_rules=%s, rules_file=%s)",
                    latest,
                    head,
                    blocks_processed_since_log,
                    len(rules.get("to_rules", [])),
                    len(rules.get("from_rules", [])),
                    rules_path,
                )
                last_progress_log = now
                blocks_processed_since_log = 0
            time.sleep(POLL_INTERVAL)
        except Exception:
            logger.exception("Error while polling; retrying soon")
            time.sleep(5)


if __name__ == "__main__":
    main()
