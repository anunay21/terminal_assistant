# AI Terminal Assistant

An AI-powered terminal assistant that turns natural language task descriptions into shell commands, executes them, and automatically fixes errors — powered by Claude Opus 4.6 with adaptive thinking, or a local Ollama model.

## Features

- **System-aware prompt enhancement** — refines your natural language input into a precise, system-tailored technical description (OS, shell, architecture included) before generating a command
- **Command generation** — produces a single, explained shell command via streaming
- **Automatic error recovery** — on failure, the AI diagnoses the error and suggests a corrected command (up to N retries)
- **Success summary** — after execution, provides a plain-English summary of what was accomplished
- **Session logging** — every interaction is written to a JSONL log file in `~/.terminal_assistant/logs/`
- **Self-bootstrapping** — installs `uv`, Python 3.14t (free-threaded), and required dependencies on first run
- **Multiple AI providers** — choose between Claude (Anthropic API) or Ollama (local inference)
- **Inline flags** — control behaviour per-task by appending flags directly to your prompt
- **Interactive command support** — TTY-requiring programs (`ssh`, `vim`, `top`, shells, REPLs, etc.) are detected automatically and handed a live terminal instead of being pipe-captured
- **Remote self-deploy** — when an `ssh` command is confirmed, offers to copy itself to the remote server via `scp` so it's ready to use immediately after connecting

## Requirements

- Python 3.12+ (any available interpreter for the initial bootstrap)
- `curl` (for installing `uv` if not present)
- **Claude provider:** An [Anthropic API key](https://console.anthropic.com/)
- **Ollama provider:** A running [Ollama](https://ollama.com/) instance

## Quick Start

```bash
python main.py
```

On first run, the assistant will:
1. Collect a system profile (OS, shell, hardware)
2. Install `uv` if not present
3. Install Python 3.14t (free-threaded) via `uv`
4. Create a virtual environment at `~/.terminal_assistant/venv`
5. Install dependencies (`anthropic`, `httpx`, `rich`)
6. Prompt you to choose an AI provider (Claude or Ollama) and supply the required credentials

Subsequent runs re-exec directly inside the managed venv.

## AI Providers

### Claude (default)

Uses [Claude Opus 4.6](https://www.anthropic.com/claude) via the Anthropic API with adaptive thinking enabled.

Set your API key interactively on first run, or via the environment:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

### Ollama (local)

Runs inference locally using any model available in your Ollama instance. No API key required.

```bash
# Start Ollama (if not already running)
ollama serve

# Pull a model
ollama pull llama3.2

# Run the assistant with Ollama
python main.py --provider ollama
```

Default Ollama settings:

| Setting | Default |
|---------|---------|
| URL | `http://localhost:11434` |
| Model | `llama3.2` |

Override with CLI flags:

```bash
python main.py --provider ollama --ollama-url http://my-server:11434 --ollama-model mistral
```

## Usage

```
usage: main.py [-h] [--dry-run] [--max-retries N] [--no-enhance]
               [--log-file PATH] [--timeout SECS] [--reconfigure]
               [--stream-delay MS] [--provider {claude,ollama}]
               [--ollama-url URL] [--ollama-model MODEL]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Show the generated command without executing it |
| `--max-retries N` | 3 | Maximum error-fix retry attempts |
| `--no-enhance` | off | Skip the prompt enhancement phase |
| `--log-file PATH` | auto | Custom session log file path |
| `--timeout SECS` | 120 | Subprocess timeout in seconds |
| `--reconfigure` | off | Re-run provider & credential setup |
| `--stream-delay MS` | 0 | Artificial token render delay (milliseconds) |
| `--provider` | saved config | AI provider to use (`claude` or `ollama`) |
| `--ollama-url URL` | saved config | Ollama server URL |
| `--ollama-model MODEL` | saved config | Ollama model name |

### Inline flags

All per-task flags can be appended directly to your prompt — no need to restart the assistant:

```
[>] Task (or 'exit'): find all log files older than 7 days --dry-run
[>] Task (or 'exit'): compress the Downloads folder --timeout 300 --max-retries 1
[>] Task (or 'exit'): list running docker containers --no-enhance
```

`--reconfigure` can also be typed inline to switch providers or update credentials without restarting:

```
[>] Task (or 'exit'): --reconfigure
```

It can be combined with a task — reconfiguration runs first, then the task proceeds with the new settings:

```
[>] Task (or 'exit'): show disk usage --reconfigure
```

### Example session

```
[>] Task (or 'exit'): find all files larger than 100MB in my home directory

Enhancing:
  On macOS 15.2 (arm64) with zsh, recursively search the home directory
  for files exceeding 100 MB and display their sizes and paths.

Enhanced: On macOS 15.2 (arm64) with zsh, recursively search...
Use enhanced prompt? [Y/n]: y

AI:
  This command uses `find` to recursively search your home directory...
  ```bash
  find ~ -type f -size +100M -exec ls -lh {} \;
  ```

Command: find ~ -type f -size +100M -exec ls -lh {} \;
Execute? [Y/n]: y
...
Summary:
  Successfully listed all files exceeding 100 MB in your home directory.
```

## Interactive Commands

Commands that require a live terminal — such as `ssh`, `sftp`, editors, pagers, monitors, REPLs, and shells — are detected automatically by their first token and executed directly on the terminal rather than through pipe capture:

| Category | Commands |
|----------|----------|
| Remote access | `ssh`, `sftp`, `telnet`, `nc`, `ncat`, `ftp`, `lftp` |
| Editors | `vim`, `vi`, `nvim`, `nano`, `emacs`, `pico`, `micro` |
| Monitors | `top`, `htop`, `btop`, `atop`, `iotop` |
| Pagers | `less`, `more`, `man` |
| REPLs | `python`, `python3`, `ipython`, `psql`, `mysql`, `sqlite3`, `mongosh`, `redis-cli` |
| Shells | `bash`, `sh`, `zsh`, `fish`, `ksh`, `dash` |

The session return code is still captured for the retry/summary flow; stdout and stderr are left empty since the user interacted directly.

## Remote Deploy

Whenever an `ssh` command is confirmed for execution, the assistant asks whether to copy itself to the remote server first:

```
Command: ssh -i ~/ssh_hetzner root@46.225.184.38
Execute? [Y/n]: y
Deploy terminal assistant to root@46.225.184.38? [y/N]: y
Copying main.py → root@46.225.184.38:~/terminal_assistant.py …
Deployed. On the server run: python ~/terminal_assistant.py
(interactive command — running directly on terminal)

root@server:~# python ~/terminal_assistant.py
```

The identity file (`-i`) is reused automatically for the `scp` transfer. On the remote server the assistant runs its normal first-time bootstrap (installs `uv`, Python, venv, deps) before starting the REPL.

## Reconfiguring

To switch providers or update credentials at any time — either at startup or from within a running session:

```bash
# CLI flag (before starting)
python main.py --reconfigure

# Inline (from within the running assistant)
[>] Task (or 'exit'): --reconfigure
```

Only the provider/credential step is repeated — the venv and dependencies are left untouched.

## File Layout

```
~/.terminal_assistant/
├── config.json          # Provider, API key, and setup state
├── system_profile.json  # Cached OS/hardware profile
├── venv/                # Managed Python virtual environment
└── logs/
    └── session_YYYYMMDD_HHMMSS.jsonl
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `anthropic` | Claude API client with streaming support |
| `httpx` | HTTP transport (also used for Ollama REST calls) |
| `rich` | Terminal UI (panels, colour output) |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key (alternative to interactive prompt / saved config) |
