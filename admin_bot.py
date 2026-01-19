import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import requests


load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RULES_FILE = os.getenv("BSC_RULES_FILE", "config/monitor_rules.json")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


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


def send_message(chat_id: str, text: str) -> None:
    if not TELEGRAM_TOKEN:
        logger.warning("Telegram token not set; cannot send messages")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text})
    if not resp.ok:
        logger.warning("Failed to send Telegram message: %s", resp.text)


def set_my_commands() -> None:
    if not TELEGRAM_TOKEN:
        logger.warning("Telegram token not set; cannot set commands")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
    commands = [
        {"command": "add_to", "description": "添加 to 规则：/add_to <地址> <方法ID> [标签]"},
        {"command": "add_from", "description": "添加 from 规则：/add_from <地址> <方法ID> [标签]"},
        {"command": "list", "description": "查看当前规则列表"},
        {"command": "remove", "description": "删除规则：/remove <to|from> <序号>"},
        {"command": "help", "description": "查看指令帮助"},
    ]
    resp = requests.post(url, json={"commands": commands})
    if not resp.ok:
        logger.warning("Failed to set commands: %s", resp.text)


def load_rules(path: Path) -> dict:
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


def save_rules(path: Path, rules: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(rules, handle, indent=2, ensure_ascii=False)
    temp_path.replace(path)


def add_rule(kind: str, address: str, method_id: str, label: Optional[str]) -> str:
    rules_path = Path(RULES_FILE)
    rules = load_rules(rules_path)
    list_key = "to_rules" if kind == "to" else "from_rules"
    address_key = "to" if kind == "to" else "from"
    rule_list = rules.get(list_key, [])

    for rule in rule_list:
        if rule.get(address_key) == address and rule.get("method_id") == method_id:
            return "Rule already exists."

    entry = {address_key: address, "method_id": method_id}
    if label:
        entry["label"] = label
    rule_list.append(entry)
    rules[list_key] = rule_list
    save_rules(rules_path, rules)
    return "Rule added."


def remove_rule(kind: str, index: int) -> str:
    rules_path = Path(RULES_FILE)
    rules = load_rules(rules_path)
    list_key = "to_rules" if kind == "to" else "from_rules"
    rule_list = rules.get(list_key, [])
    if index < 1 or index > len(rule_list):
        return "Index out of range."
    removed = rule_list.pop(index - 1)
    rules[list_key] = rule_list
    save_rules(rules_path, rules)
    label = removed.get("label")
    if label:
        return f"Removed {kind} rule #{index} ({label})."
    return f"Removed {kind} rule #{index}."


def format_rules(rules: dict) -> str:
    to_rules = rules.get("to_rules", [])
    from_rules = rules.get("from_rules", [])
    lines = []
    lines.append("to_rules:")
    if to_rules:
        for idx, rule in enumerate(to_rules, start=1):
            label = rule.get("label")
            suffix = f" label={label}" if label else ""
            lines.append(f"{idx}. {rule.get('to')} {rule.get('method_id')}{suffix}")
    else:
        lines.append("(empty)")

    lines.append("")
    lines.append("from_rules:")
    if from_rules:
        for idx, rule in enumerate(from_rules, start=1):
            label = rule.get("label")
            suffix = f" label={label}" if label else ""
            lines.append(f"{idx}. {rule.get('from')} {rule.get('method_id')}{suffix}")
    else:
        lines.append("(empty)")
    return "\n".join(lines)


def help_text() -> str:
    return (
        "Commands:\n"
        "/add_to <to_address> <method_id> [label]\n"
        "/add_from <from_address> <method_id> [label]\n"
        "/list\n"
        "/remove <to|from> <index>\n"
        "/help"
    )


def handle_command(text: str) -> Optional[str]:
    if not text:
        return None
    parts = text.strip().split()
    if not parts:
        return None
    command = parts[0].split("@")[0].lower()
    args = parts[1:]

    if command in {"/start", "/help"}:
        return help_text()
    if command == "/list":
        rules = load_rules(Path(RULES_FILE))
        return format_rules(rules)
    if command in {"/add_to", "/add_from"}:
        if len(args) < 2:
            return "Usage: /add_to <to_address> <method_id> [label]"
        address = normalize_address(args[0])
        method_id = normalize_method_id(args[1])
        label = " ".join(args[2:]).strip() if len(args) > 2 else None
        if not address:
            return "Invalid address."
        if not method_id:
            return "Invalid method_id."
        kind = "to" if command == "/add_to" else "from"
        return add_rule(kind, address, method_id, label)
    if command == "/remove":
        if len(args) < 2:
            return "Usage: /remove <to|from> <index>"
        kind = args[0].lower()
        if kind not in {"to", "from"}:
            return "Usage: /remove <to|from> <index>"
        try:
            index = int(args[1])
        except ValueError:
            return "Index must be a number."
        return remove_rule(kind, index)
    return "Unknown command. Use /help."


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is required")

    authorized_chat_id = str(TELEGRAM_CHAT_ID)
    offset = 0
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

    logger.info("Admin bot started. Rules file: %s", RULES_FILE)
    set_my_commands()

    while True:
        try:
            resp = requests.get(url, params={"timeout": 30, "offset": offset}, timeout=35)
            if not resp.ok:
                logger.warning("Failed to fetch updates: %s", resp.text)
                time.sleep(2)
                continue
            data = resp.json()
            if not data.get("ok"):
                logger.warning("Telegram API error: %s", data)
                time.sleep(2)
                continue
            updates = data.get("result", [])
            for update in updates:
                offset = update.get("update_id", offset) + 1
                message = update.get("message")
                if not message:
                    continue
                chat_id = str(message.get("chat", {}).get("id", ""))
                if chat_id != authorized_chat_id:
                    send_message(chat_id, "Unauthorized.")
                    continue
                text = message.get("text", "")
                response = handle_command(text)
                if response:
                    send_message(chat_id, response)
        except Exception:
            logger.exception("Error while polling; retrying soon")
            time.sleep(2)


if __name__ == "__main__":
    main()
