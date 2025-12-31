# BSC 交易监控器

轮询 Binance Smart Chain（币安智能链）上指定合约地址和方法 ID 的调用，并在匹配时发送 Telegram 通知。

## 安装依赖

### 使用 pip

```bash
pip install -r requirements.txt
```

### 使用 uv（推荐）

[uv](https://github.com/astral-sh/uv) 是一个快速的 Python 包管理器。

```bash
# 安装 uv（如果还没有）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境并安装依赖
uv venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

uv pip install -r requirements.txt
```

## 环境配置

复制示例配置文件并填入你的配置：

```bash
cp .env.example .env
```

然后编辑 `.env` 文件，配置以下参数：

| 变量 | 是否必需 | 默认值 | 说明 |
|------|----------|--------|------|
| `BSC_RPC_URL` | 否 | `https://bsc-dataseed.binance.org` | HTTPS RPC 端点 |
| `BSC_CONTRACT` | 否 | `0x56a3bF66db83e59d13DFED48205Bb84c33B08d1b` | 要监控的合约地址 |
| `BSC_METHOD_ID` | 否 | `0xfd5c9779` | 4 字节方法选择器（带 `0x` 前缀） |
| `POLL_INTERVAL` | 否 | `3` | 检查新区块的间隔秒数 |
| `TELEGRAM_BOT_TOKEN` | **是** | - | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | **是** | - | Telegram 聊天 ID |
| `START_BLOCK` | 否 | - | 从指定的历史区块号开始扫描（用于测试） |
| `EXIT_AFTER_CATCHUP` | 否 | `false` | 如果为 `true`，扫描到链头后退出 |
| `LOG_PROGRESS_INTERVAL` | 否 | `60` | 扫描时记录进度日志的间隔秒数；设为 `0` 禁用 |

## 运行

```bash
uv run monitor.py
```

脚本从当前最新区块开始，检查每个新区块中 `to` 地址与 `BSC_CONTRACT` 匹配且 `input` 以 `BSC_METHOD_ID` 开头的交易。当发现匹配时，会向配置的 Telegram 聊天发送消息。

> **注意**：BSC 使用 PoA 共识机制，脚本已注入 `geth_poa_middleware` 以确保区块解析正常。

## 部署与后台运行

为了让脚本在 VPS 上长期运行（即使断开 SSH），推荐使用 Systemd，或者使用 Screen/Tmux。

### 方式一：使用 Systemd (推荐)

Systemd 可以让脚本作为系统服务运行，支持开机自启和崩溃自动重启。

1. 修改 `binance-monitor.service` 文件中的路径和用户：
   ```ini
   [Service]
   User=root
   WorkingDirectory=/path/to/your/BinanceIDO
   ExecStart=/root/.cargo/bin/uv run monitor.py
   ```
   *注意：请使用 `which uv` 查找 `uv` 的绝对路径。*

2. 复制服务文件到系统目录：
   ```bash
   sudo cp binance-monitor.service /etc/systemd/system/
   ```

3. 启动服务并设置开机自启：
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable binance-monitor
   sudo systemctl start binance-monitor
   ```

4. 查看日志：
   ```bash
   sudo journalctl -u binance-monitor -f
   ```

### 方式二：使用 Screen/Tmux

适合临时调试或不熟悉 Systemd 的用户。

```bash
# 安装 screen (Ubuntu/Debian)
sudo apt install screen

# 创建一个新会话
screen -S binance

# 在新窗口中运行脚本
uv run monitor.py

# 按 Ctrl+A 然后按 D 键，将窗口挂起（后台运行）
# 此时可以安全断开 SSH 连接
```

恢复窗口：
```bash
screen -r binance
```

### 方式三：使用 Nohup

最简单的后台运行方式。

```bash
nohup uv run monitor.py > monitor.log 2>&1 &
```

查看日志：
```bash
tail -f monitor.log
```

## 许可证

本项目采用 [MIT License](LICENSE) 开源协议。
