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

USAGE_ADD_TO = "/add_to <to_address> <method_id> [label]"
USAGE_ADD_FROM = "/add_from <from_address> <method_id> [label]"
USAGE_REMOVE = "/remove <to|from> <index>"
EXAMPLE_ADD_TO = "/add_to 0x56a3bf66db83e59d13dfed48205bb84c33b08d1b 0xfd5c9779 IDO created"
EXAMPLE_ADD_FROM = "/add_from 0xee7b429ea01f76102f053213463d4e95d5d24ae8 0x40c10f19 Prime Key minted"
EXAMPLE_REMOVE = "/remove to 1"


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


def format_error(title: str, usage: Optional[str] = None, example: Optional[str] = None) -> str:
    lines = [f"❌ {title}"]
    if usage:
        lines.append(f"用法: {usage}")
    if example:
        lines.append(f"示例: {example}")
    return "\n".join(lines)


def format_success(title: str, lines: Optional[list] = None) -> str:
    message_lines = [f"✅ {title}"]
    if lines:
        message_lines.extend(lines)
    return "\n".join(message_lines)


def format_warning(title: str, lines: Optional[list] = None) -> str:
    message_lines = [f"⚠️ {title}"]
    if lines:
        message_lines.extend(lines)
    return "\n".join(message_lines)


def format_rule_block(kind: str, rule: dict, index: Optional[int] = None) -> list:
    label = rule.get("label") or "未命名"
    address_key = "to" if kind == "to" else "from"
    address = rule.get(address_key, "-")
    method_id = rule.get("method_id", "-")
    header = f"{index}) {label}" if index is not None else label
    return [
        header,
        f"   {address_key}: {address}",
        f"   method: {method_id}",
    ]


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
            lines = format_rule_block(kind, rule)
            return format_warning("规则已存在", lines)

    entry = {address_key: address, "method_id": method_id}
    if label:
        entry["label"] = label
    rule_list.append(entry)
    rules[list_key] = rule_list
    save_rules(rules_path, rules)
    return format_success("已添加规则", format_rule_block(kind, entry))


def remove_rule(kind: str, index: int) -> str:
    rules_path = Path(RULES_FILE)
    rules = load_rules(rules_path)
    list_key = "to_rules" if kind == "to" else "from_rules"
    rule_list = rules.get(list_key, [])
    if index < 1 or index > len(rule_list):
        return format_error("序号超出范围", USAGE_REMOVE, EXAMPLE_REMOVE)
    removed = rule_list.pop(index - 1)
    rules[list_key] = rule_list
    save_rules(rules_path, rules)
    lines = format_rule_block(kind, removed)
    lines.insert(0, f"序号: {index}")
    return format_success(f"已删除 {kind} 规则", lines)


def format_rules(rules: dict) -> str:
    to_rules = rules.get("to_rules", [])
    from_rules = rules.get("from_rules", [])
    lines = []
    lines.append("🧾 规则列表")
    lines.append("")
    lines.append(f"to_rules ({len(to_rules)}):")
    if to_rules:
        for idx, rule in enumerate(to_rules, start=1):
            lines.extend(format_rule_block("to", rule, idx))
            lines.append("")
    else:
        lines.append("  （暂无）")

    lines.append(f"from_rules ({len(from_rules)}):")
    if from_rules:
        for idx, rule in enumerate(from_rules, start=1):
            lines.extend(format_rule_block("from", rule, idx))
            lines.append("")
    else:
        lines.append("  （暂无）")
    return "\n".join(line for line in lines if line != "")


def help_text() -> str:
    return (
        "🧭 指令帮助\n"
        f"1) {USAGE_ADD_TO}\n"
        f"   示例: {EXAMPLE_ADD_TO}\n"
        f"2) {USAGE_ADD_FROM}\n"
        f"   示例: {EXAMPLE_ADD_FROM}\n"
        "3) /list\n"
        "   示例: /list\n"
        f"4) {USAGE_REMOVE}\n"
        f"   示例: {EXAMPLE_REMOVE}\n"
        "5) /help\n"
        "   示例: /help"
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
            usage = USAGE_ADD_TO if command == "/add_to" else USAGE_ADD_FROM
            example = EXAMPLE_ADD_TO if command == "/add_to" else EXAMPLE_ADD_FROM
            return format_error("参数不足", usage, example)
        address = normalize_address(args[0])
        method_id = normalize_method_id(args[1])
        label = " ".join(args[2:]).strip() if len(args) > 2 else None
        if not address:
            usage = USAGE_ADD_TO if command == "/add_to" else USAGE_ADD_FROM
            example = EXAMPLE_ADD_TO if command == "/add_to" else EXAMPLE_ADD_FROM
            return format_error("地址格式不正确", usage, example)
        if not method_id:
            usage = USAGE_ADD_TO if command == "/add_to" else USAGE_ADD_FROM
            example = EXAMPLE_ADD_TO if command == "/add_to" else EXAMPLE_ADD_FROM
            return format_error("方法 ID 格式不正确", usage, example)
        kind = "to" if command == "/add_to" else "from"
        return add_rule(kind, address, method_id, label)
    if command == "/remove":
        if len(args) < 2:
            return format_error("参数不足", USAGE_REMOVE, EXAMPLE_REMOVE)
        kind = args[0].lower()
        if kind not in {"to", "from"}:
            return format_error("类型必须是 to 或 from", USAGE_REMOVE, EXAMPLE_REMOVE)
        try:
            index = int(args[1])
        except ValueError:
            return format_error("序号必须是数字", USAGE_REMOVE, EXAMPLE_REMOVE)
        return remove_rule(kind, index)
    return format_error("未知命令", "/help", "/help")


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
                    send_message(chat_id, "🚫 未授权的聊天。")
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
