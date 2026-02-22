# AI Terminal Assistant

An AI-powered terminal assistant that turns natural language task descriptions into shell commands, executes them, and automatically fixes errors — powered by Claude Opus 4.6 with adaptive thinking.

## Features

- **Prompt enhancement** — refines your natural language input into a precise technical description before generating a command
- **Command generation** — produces a single, explained shell command via Claude streaming
- **Automatic error recovery** — on failure, Claude diagnoses the error and suggests a corrected command (up to N retries)
- **Success summary** — after execution, provides a plain-English summary of what was accomplished
- **Session logging** — every interaction is written to a JSONL log file in `~/.terminal_assistant/logs/`
- **Self-bootstrapping** — installs `uv`, Python 3.14t (free-threaded), and required dependencies on first run

## Requirements

- Python 3.12+ (any available interpreter for the initial bootstrap)
- An [Anthropic API key](https://console.anthropic.com/)
- `curl` (for installing `uv` if not present)

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
6. Prompt for your Anthropic API key (or read `ANTHROPIC_API_KEY` from the environment)

Subsequent runs re-exec directly inside the managed venv.

## Usage

```
usage: main.py [-h] [--dry-run] [--max-retries N] [--no-enhance]
               [--log-file PATH] [--timeout SECS] [--reconfigure]
               [--stream-delay MS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Show the generated command without executing it |
| `--max-retries N` | 3 | Maximum error-fix retry attempts |
| `--no-enhance` | off | Skip the prompt enhancement phase |
| `--log-file PATH` | auto | Custom session log file path |
| `--timeout SECS` | 120 | Subprocess timeout in seconds |
| `--reconfigure` | off | Re-run first-time setup |
| `--stream-delay MS` | 0 | Artificial token render delay (milliseconds) |

### Example session

```
[>] Task (or 'exit'): find all files larger than 100MB in my home directory

Enhancing:
  List all files in the home directory tree that exceed 100 MB in size, ...

Enhanced: List all files in the home directory tree...
Use enhanced prompt? [Y/n]: y

Claude:
  This command uses `find` to recursively search your home directory...
  ```bash
  find ~ -type f -size +100M
  ```

Command: find ~ -type f -size +100M
Execute? [Y/n]: y
...
Summary:
  Successfully listed all files exceeding 100 MB in your home directory.
```

## File Layout

```
~/.terminal_assistant/
├── config.json          # API key and setup state
├── system_profile.json  # Cached OS/hardware profile
├── venv/                # Managed Python virtual environment
└── logs/
    └── session_YYYYMMDD_HHMMSS.jsonl
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `anthropic` | Claude API client with streaming support |
| `httpx` | HTTP transport |
| `rich` | Terminal UI (panels, colour output) |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | API key (alternative to interactive prompt / saved config) |

## Reconfiguring

To reset setup or update your API key:

```bash
python main.py --reconfigure
```
