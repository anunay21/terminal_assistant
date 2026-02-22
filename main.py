#!/usr/bin/env python3
"""
AI-Powered Terminal Assistant
Self-bootstrapping | Python 3.14t (free-threaded) | uv | Claude Opus 4.6
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ---------- Directory layout ----------
ASSISTANT_DIR = Path.home() / ".terminal_assistant"
CONFIG_FILE   = ASSISTANT_DIR / "config.json"
PROFILE_FILE  = ASSISTANT_DIR / "system_profile.json"
VENV_DIR      = ASSISTANT_DIR / "venv"
LOG_DIR       = ASSISTANT_DIR / "logs"

_IS_WIN  = sys.platform == "win32"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if _IS_WIN else "bin/python")

PYTHON_TARGET = "3.14t"   # free-threaded build requested by spec
MODEL         = "claude-opus-4-6"

DEFAULT_OLLAMA_URL   = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"

# ============================================================
# SECTION 1 — Utilities (pure stdlib, always importable)
# ============================================================

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    ASSISTANT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    CONFIG_FILE.chmod(0o600)


def in_venv() -> bool:
    """True if we are already executing inside the assistant venv."""
    if not VENV_PYTHON.exists():
        return False
    try:
        return Path(sys.executable).resolve() == VENV_PYTHON.resolve()
    except OSError:
        return False


def _sh(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ============================================================
# SECTION 2 — Bootstrap (stdlib only; runs before the venv exists)
# ============================================================

def collect_system_profile() -> dict:
    """Probe the OS and hardware; persist to PROFILE_FILE."""
    p: dict = {}
    p["platform"]         = platform.system()
    p["platform_release"] = platform.release()
    p["machine"]          = platform.machine()
    p["hostname"]         = platform.node()
    p["user"]             = os.environ.get("USER") or getpass.getuser()
    p["home"]             = str(Path.home())
    p["shell"]            = os.environ.get("SHELL") or shutil.which("bash") or "sh"

    # Human-readable OS type (resolved further below for Linux distros)
    sys_name = platform.system()
    if sys_name == "Darwin":
        mac_ver = platform.mac_ver()[0]
        p["os_type"] = f"macOS {mac_ver}" if mac_ver else "macOS"
    elif sys_name == "Windows":
        p["os_type"] = f"Windows {platform.release()}"
    else:
        p["os_type"] = f"Linux {platform.release()}"

    # Ubuntu / Linux distro info
    if Path("/etc/os-release").exists():
        info: dict = {}
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                info[k] = v.strip('"')
        p["os_info"] = info
        # Refine os_type from distro name (e.g. "Ubuntu 22.04.3 LTS")
        if "PRETTY_NAME" in info:
            p["os_type"] = info["PRETTY_NAME"]
        elif "NAME" in info:
            p["os_type"] = f"{info['NAME']} {info.get('VERSION', '')}".strip()

    # Timezone
    try:
        p["timezone"] = _sh(["date", "+%Z"]).stdout.strip()
    except Exception:
        p["timezone"] = "unknown"

    p["locale"] = os.environ.get("LANG", "unknown")

    # CPU cores
    try:
        import multiprocessing
        p["cpu_cores"] = multiprocessing.cpu_count()
    except Exception:
        p["cpu_cores"] = 1

    # RAM (Linux /proc/meminfo)
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    p["memory_kb"] = int(line.split()[1])
                    break
    except Exception:
        pass

    # Installed package managers
    p["package_managers"] = {
        pm: bool(shutil.which(pm))
        for pm in ("apt", "snap", "flatpak", "brew")
    }

    # Python interpreters already present
    p["python_versions"] = [
        v for v in ("python3", "python3.12", "python3.13", "python3.14", "python3.14t")
        if shutil.which(v)
    ]

    ASSISTANT_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(p, indent=2))
    return p


def _extend_path() -> None:
    """Add common uv install directories to PATH for the current process."""
    for d in (
        Path.home() / ".local" / "bin",
        Path.home() / ".cargo"  / "bin",
    ):
        if d.exists() and str(d) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{d}:{os.environ.get('PATH', '')}"


def install_uv() -> bool:
    _extend_path()
    if shutil.which("uv"):
        print("  [ok] uv already installed")
        return True
    print("  Installing uv via official installer…")
    r = subprocess.run(
        ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
        capture_output=True, text=True,
    )
    _extend_path()
    if shutil.which("uv"):
        print("  [ok] uv installed")
        return True
    print(f"  [warn] uv install failed: {r.stderr.strip()[:200]}")
    return False


def install_python_3_14t() -> bool:
    """Install the free-threaded Python 3.14t build via uv."""
    uv = shutil.which("uv")
    if not uv:
        return False
    r = _sh([uv, "python", "find", PYTHON_TARGET])
    if r.returncode == 0 and r.stdout.strip():
        print(f"  [ok] Python {PYTHON_TARGET} already present")
        py = r.stdout.strip()
        chk = _sh([py, "-c", "import sys; print(sys._is_gil_enabled())"])
        if chk.stdout.strip() == "False":
            print("  [ok] GIL disabled — true free-threading confirmed")
        return True
    print(f"  Installing Python {PYTHON_TARGET} (free-threaded)…")
    r2 = subprocess.run(
        [uv, "python", "install", PYTHON_TARGET],
        capture_output=True, text=True,
    )
    if r2.returncode == 0:
        print(f"  [ok] Python {PYTHON_TARGET} installed")
        return True
    print(f"  [warn] Could not install Python {PYTHON_TARGET}: {r2.stderr.strip()[:200]}")
    return False


def create_venv() -> bool:
    """Create the assistant venv, trying Python versions from newest to oldest."""
    if VENV_PYTHON.exists():
        print("  [ok] venv already exists")
        return True
    uv = shutil.which("uv")
    if uv:
        for ver in (PYTHON_TARGET, "3.13", "3.12", "3"):
            r = subprocess.run(
                [uv, "venv", str(VENV_DIR), "--python", ver],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                print(f"  [ok] venv created (Python {ver})")
                return True
    # Fallback: stdlib venv
    r = subprocess.run(
        [sys.executable, "-m", "venv", str(VENV_DIR)],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        print("  [ok] venv created (stdlib fallback)")
        return True
    print(f"  [error] venv creation failed: {r.stderr.strip()[:200]}")
    return False


def install_deps() -> bool:
    """Install anthropic, httpx, and rich into the assistant venv."""
    deps = ["anthropic", "httpx", "rich"]
    uv = shutil.which("uv")
    if uv:
        r = subprocess.run(
            [uv, "pip", "install", *deps, "--python", str(VENV_PYTHON)],
            capture_output=True, text=True,
        )
    else:
        pip = VENV_DIR / ("Scripts/pip" if _IS_WIN else "bin/pip")
        r = subprocess.run([str(pip), "install", *deps], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  [ok] dependencies installed: {', '.join(deps)}")
        return True
    print(f"  [error] dependency install failed: {r.stderr.strip()[:300]}")
    return False


def setup_api_key(cfg: dict) -> dict:
    if cfg.get("api_key"):
        print("  [ok] API key already saved")
        return cfg
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        print("  [ok] Using ANTHROPIC_API_KEY from environment")
        cfg["api_key"] = env_key
        return cfg
    print()
    print("  Get your key at https://console.anthropic.com/")
    try:
        key = getpass.getpass("  Enter Anthropic API key: ").strip()
    except (EOFError, Exception):
        # Non-TTY fallback (e.g. piped input or IDE terminal)
        try:
            key = input("  Enter Anthropic API key (visible): ").strip()
        except (EOFError, KeyboardInterrupt):
            key = ""
    if not key:
        print("  [error] No API key provided — aborting")
        sys.exit(1)
    cfg["api_key"] = key
    return cfg


def setup_provider(cfg: dict) -> dict:
    """Prompt user to choose AI provider."""
    print()
    print("  Choose AI provider:")
    print("    1) Claude (Anthropic API)  — cloud, requires API key")
    print("    2) Ollama                  — local, no API key needed")
    while True:
        try:
            choice = input("  Enter choice [1/2] (default: 1): ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "1"
        if choice in ("", "1"):
            cfg["provider"] = "claude"
            break
        elif choice == "2":
            cfg["provider"] = "ollama"
            break
        print("  Please enter 1 or 2.")
    return cfg


def setup_ollama_config(cfg: dict) -> dict:
    """Configure Ollama base URL and model."""
    current_url   = cfg.get("ollama_url",   DEFAULT_OLLAMA_URL)
    current_model = cfg.get("ollama_model", DEFAULT_OLLAMA_MODEL)
    try:
        url = input(f"  Ollama base URL [{current_url}]: ").strip() or current_url
    except (EOFError, KeyboardInterrupt):
        url = current_url
    try:
        model = input(f"  Ollama model    [{current_model}]: ").strip() or current_model
    except (EOFError, KeyboardInterrupt):
        model = current_model
    cfg["ollama_url"]   = url
    cfg["ollama_model"] = model
    print(f"  [ok] Ollama configured: {url}  model={model}")
    return cfg


def run_bootstrap() -> None:
    """Run the full first-time setup sequence."""
    print()
    print("=" * 60)
    print("  AI Terminal Assistant — First-Run Setup")
    print("=" * 60)
    ASSISTANT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/5] Collecting system profile…")
    p = collect_system_profile()
    print(f"  {p.get('platform')} {p.get('machine')} — {p.get('hostname')}")
    print(f"  Shell: {p.get('shell')}  |  Locale: {p.get('locale')}")

    print("\n[2/5] Checking uv package manager…")
    install_uv()

    print(f"\n[3/5] Installing Python {PYTHON_TARGET} (free-threaded)…")
    install_python_3_14t()

    print("\n[4/5] Setting up virtual environment & dependencies…")
    if not create_venv():
        print("[error] Cannot create venv — aborting")
        sys.exit(1)
    if not install_deps():
        print("[error] Cannot install dependencies — aborting")
        sys.exit(1)

    print("\n[5/5] Provider & API key configuration…")
    cfg = load_config()
    cfg = setup_provider(cfg)
    if cfg.get("provider") == "ollama":
        cfg = setup_ollama_config(cfg)
    else:
        cfg = setup_api_key(cfg)
    cfg["first_run_complete"] = True
    cfg["setup_date"] = datetime.now().isoformat()
    save_config(cfg)

    print()
    print("=" * 60)
    print("  Setup complete!")
    print(f"  Config  : {CONFIG_FILE}")
    print(f"  Profile : {PROFILE_FILE}")
    print(f"  Venv    : {VENV_DIR}")
    print(f"  Logs    : {LOG_DIR}")
    print("=" * 60)
    print()


# ============================================================
# SECTION 3 — Main application (runs inside the venv)
# ============================================================

def run_app(args: argparse.Namespace, cfg: dict, profile: dict) -> None:
    # These imports are only available after the venv is set up
    import anthropic                          # noqa: PLC0415
    import httpx                              # noqa: PLC0415
    from rich.console import Console          # noqa: PLC0415
    from rich.panel import Panel              # noqa: PLC0415

    console = Console()

    # ── Provider selection ───────────────────────────────────────────────────
    provider     = args.provider or cfg.get("provider", "claude")
    ollama_url   = args.ollama_url   or cfg.get("ollama_url",   DEFAULT_OLLAMA_URL)
    ollama_model = args.ollama_model or cfg.get("ollama_model", DEFAULT_OLLAMA_MODEL)
    client       = None

    if provider == "claude":
        api_key = cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            console.print("[red]No API key found. Run with --reconfigure.[/red]")
            sys.exit(1)
        client = anthropic.Anthropic(api_key=api_key)

    # ── Queues & synchronisation ────────────────────────────────────────────
    token_q: queue.Queue = queue.Queue()   # Thread 2 → Thread 1
    log_q:   queue.Queue = queue.Queue()   # Thread 1 → Thread 4
    cancel  = threading.Event()

    # ── Thread 4 — Logger ──────────────────────────────────────────────────
    if args.log_file:
        session_log = Path(args.log_file)
    else:
        session_log = LOG_DIR / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

    def _logger() -> None:
        with open(session_log, "w") as fh:
            while True:
                try:
                    entry = log_q.get(timeout=1)
                except queue.Empty:
                    continue
                if entry is None:
                    break
                fh.write(json.dumps(entry) + "\n")
                fh.flush()

    threading.Thread(target=_logger, daemon=True, name="logger").start()

    def log(event: str, **kw) -> None:
        log_q.put({"ts": datetime.now().isoformat(), "event": event, **kw})

    # ── Thread 5 — Context (already loaded; log it) ─────────────────────────
    log("session_start", profile_keys=list(profile.keys()), model=MODEL)

    # ── System prompt ───────────────────────────────────────────────────────
    os_name = (
        profile.get("os_type")
        or (profile.get("os_info") or {}).get("PRETTY_NAME")
        or f"{profile.get('platform', 'Linux')} {profile.get('platform_release', '')}"
    )

    # Build a rich system context from the captured profile
    _hw = f"CPU: {profile['cpu_cores']} cores" if "cpu_cores" in profile else ""
    if "memory_kb" in profile:
        _hw += f"  |  RAM: {round(profile['memory_kb'] / 1024 / 1024, 1)} GB"
    _pkgs = [pm for pm, ok in (profile.get("package_managers") or {}).items() if ok]

    _profile_lines = [
        f"OS: {os_name}  |  Arch: {profile.get('machine', '?')}  |  Shell: {profile.get('shell', 'bash')}",
        f"User: {profile.get('user', '?')}@{profile.get('hostname', '?')}  |  Timezone: {profile.get('timezone', 'unknown')}",
    ]
    if _hw:
        _profile_lines.append(_hw)
    if _pkgs:
        _profile_lines.append(f"Package managers: {', '.join(_pkgs)}")
    _profile_ctx = "\n".join(_profile_lines)

    SYSTEM = (
        f"You are an AI-powered terminal assistant.\n"
        f"{_profile_ctx}\n\n"
        "Workflow:\n"
        "1. Prompt enhancement — refine the user's request into a precise 1–2 sentence "
        "technical description. Do NOT generate a command in this phase.\n"
        "2. Command generation — produce ONE shell command inside a ```bash block, "
        "with a brief explanation and any risk notes.\n"
        "3. Error fix — diagnose the failure briefly, then emit a corrected ```bash block.\n"
        "4. Summary — after success, give a 1–2 sentence plain-English summary of what "
        "was accomplished.\n\n"
        "Rules:\n"
        "• Always use exactly one ```bash ... ``` block when emitting a command.\n"
        "• Prefer safe, non-destructive operations; call out destructive steps explicitly.\n"
        "• Keep all explanations concise."
    )

    # ── Thread 2 — AI streaming (Claude or Ollama) ──────────────────────────
    def _stream_claude(messages: list[dict]) -> None:
        """Background thread: Claude SSE stream → token_q."""
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=8192,
                thinking={"type": "adaptive"},
                system=SYSTEM,
                messages=messages,
            ) as stream:
                for event in stream:
                    if cancel.is_set():
                        break
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "text"):
                            token_q.put(("tok", delta.text))
            token_q.put(("done", None))
        except Exception as exc:
            token_q.put(("err", str(exc)))

    def _stream_ollama(messages: list[dict]) -> None:
        """Background thread: Ollama streaming chat → token_q."""
        try:
            payload = {
                "model": ollama_model,
                "messages": [{"role": "system", "content": SYSTEM}]
                           + [{"role": m["role"], "content": m["content"]}
                              for m in messages],
                "stream": True,
            }
            with httpx.stream(
                "POST", f"{ollama_url}/api/chat",
                json=payload, timeout=120,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if cancel.is_set():
                        break
                    if not line:
                        continue
                    data = json.loads(line)
                    text = (data.get("message") or {}).get("content", "")
                    if text:
                        token_q.put(("tok", text))
                    if data.get("done"):
                        break
            token_q.put(("done", None))
        except Exception as exc:
            token_q.put(("err", str(exc)))

    def stream(messages: list[dict], label: str) -> str:
        """
        Spawn Thread 2, drain token_q in Thread 1 (UI), and return the
        full accumulated text.  Tokens are written to stdout in real time.
        """
        cancel.clear()
        target = _stream_claude if provider == "claude" else _stream_ollama
        t = threading.Thread(
            target=target, args=(messages,),
            name="ai-stream", daemon=True,
        )
        t.start()

        buf = ""
        sys.stdout.write(f"\n{label}:\n  ")
        sys.stdout.flush()

        while True:
            try:
                kind, data = token_q.get(timeout=60)
            except queue.Empty:
                sys.stdout.write("\n")
                console.print("[red][timeout waiting for AI response][/red]")
                break
            if kind == "tok":
                # Mid-stream: append to rolling buffer for command extraction
                buf += data
                sys.stdout.write(data)
                sys.stdout.flush()
                if args.stream_delay:
                    time.sleep(args.stream_delay / 1000)
            elif kind == "done":
                sys.stdout.write("\n")
                sys.stdout.flush()
                break
            elif kind == "err":
                sys.stdout.write("\n")
                console.print(f"[red]Stream error: {data}[/red]")
                break

        t.join(timeout=5)
        return buf

    # ── Command extractor (regex on rolling buffer / full text) ─────────────
    _CMD_RE = re.compile(
        r"```(?:bash|sh|shell)?\s*\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE,
    )

    def extract_command(text: str) -> str | None:
        m = _CMD_RE.search(text)
        return m.group(1).strip() if m else None

    # ── Thread 3 — Command execution ────────────────────────────────────────
    def execute(cmd: str) -> tuple[int, str, str]:
        """Run cmd in a subprocess; stream stdout/stderr live; return (rc, out, err)."""
        log("exec_start", command=cmd)
        out_lines: list[str] = []
        err_lines: list[str] = []

        try:
            proc = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )

            def _read(pipe, lines: list[str]) -> None:
                for ln in pipe:
                    lines.append(ln)
                    sys.stdout.write(ln)
                    sys.stdout.flush()

            t_out = threading.Thread(
                target=_read, args=(proc.stdout, out_lines), daemon=True,
            )
            t_err = threading.Thread(
                target=_read, args=(proc.stderr, err_lines), daemon=True,
            )
            t_out.start()
            t_err.start()
            t_out.join(timeout=args.timeout)
            t_err.join(timeout=args.timeout)
            rc = proc.wait(timeout=10)

        except subprocess.TimeoutExpired:
            proc.kill()
            out_lines.append("[process killed: timeout]\n")
            rc = -1
        except Exception as exc:
            err_lines.append(f"{exc}\n")
            rc = -1

        stdout = "".join(out_lines)
        stderr = "".join(err_lines)
        log("exec_end", command=cmd, rc=rc)
        return rc, stdout, stderr

    # ── Main interaction loop (Thread 1 — UI) ───────────────────────────────
    os_display = (
        profile.get("os_type")
        or (profile.get("os_info") or {}).get("PRETTY_NAME")
        or profile.get("platform", "system")
    )
    if provider == "claude":
        provider_info = f"Claude {MODEL} + adaptive thinking"
    else:
        provider_info = f"Ollama {ollama_model}  ({ollama_url})"
    console.print(
        Panel(
            f"[bold green]AI Terminal Assistant[/bold green]  •  {provider_info}\n"
            f"[dim]{os_display}  •  session log: {session_log}[/dim]\n"
            "\n[bold]Options:[/bold]\n"
            "  [cyan]--dry-run[/cyan]              Show command without executing\n"
            "  [cyan]--no-enhance[/cyan]           Skip prompt enhancement phase\n"
            "  [cyan]--max-retries N[/cyan]        Max error-fix retries [dim](default: 3)[/dim]\n"
            "  [cyan]--timeout SECS[/cyan]         Subprocess timeout in seconds [dim](default: 120)[/dim]\n"
            "  [cyan]--log-file PATH[/cyan]        Custom session log file path\n"
            "  [cyan]--stream-delay MS[/cyan]      Artificial token render delay in ms\n"
            "  [cyan]--provider PROVIDER[/cyan]    Override AI provider: [dim]claude[/dim] | [dim]ollama[/dim]\n"
            "  [cyan]--ollama-url URL[/cyan]       Ollama base URL [dim](default: http://localhost:11434)[/dim]\n"
            "  [cyan]--ollama-model MODEL[/cyan]   Ollama model name [dim](default: llama3.2)[/dim]\n"
            "  [cyan]--reconfigure[/cyan]          Re-run first-time setup\n"
            "\n[dim]Type 'exit', 'quit', or 'q' to quit  •  Ctrl-C to force exit[/dim]",
            expand=False,
        )
    )

    def _sigint(sig, frame) -> None:  # noqa: ANN001
        cancel.set()
        sys.stdout.write("\n[Ctrl-C] Exiting...\n")
        sys.stdout.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    while True:
        try:
            user_in = input("\n[>] Task (or 'exit'): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_in or user_in.lower() in ("exit", "quit", "q"):
            break

        cancel.clear()
        log("user_input", text=user_in)

        # ── Phase 1: Prompt enhancement ─────────────────────────────────────
        if not args.no_enhance:
            enh_resp = stream(
                [{
                    "role": "user",
                    "content": (
                        "Refine this terminal task into a precise 1–2 sentence technical "
                        "description. Do NOT generate a command yet.\n\n"
                        f"Task: {user_in}"
                    ),
                }],
                "Enhancing",
            )
            log("enhanced", original=user_in, enhanced=enh_resp)
            console.print(f"\n[dim]Enhanced:[/dim] {enh_resp.strip()}")
            try:
                yn = input("Use enhanced prompt? [Y/n]: ").strip().lower()
                task = user_in if yn in ("n", "no") else enh_resp.strip() or user_in
            except (EOFError, KeyboardInterrupt):
                task = user_in
        else:
            task = user_in

        # ── Phase 2: Command generation ──────────────────────────────────────
        gen_resp = stream(
            [{
                "role": "user",
                "content": (
                    f"Generate a shell command for: {task}\n\n"
                    "1. Briefly explain what the command does (1–2 sentences).\n"
                    "2. Show the command in a ```bash block.\n"
                    "3. Note any risks or side effects."
                ),
            }],
            "AI",
        )
        log("generated", text=gen_resp)

        command = extract_command(gen_resp)
        if not command:
            console.print("[yellow]No command found in AI response.[/yellow]")
            continue

        console.print(f"\n[bold]Command:[/bold] [cyan]{command}[/cyan]")

        if args.dry_run:
            log("dry_run", command=command)
            console.print("[dim](dry-run — not executing)[/dim]")
            continue

        try:
            yn = input("Execute? [Y/n]: ").strip().lower()
            if yn in ("n", "no"):
                log("skipped", command=command)
                continue
        except (EOFError, KeyboardInterrupt):
            continue

        # ── Phase 3: Execution + error loop ─────────────────────────────────
        console.print(f"\n[dim]{'─' * 52}[/dim]")
        success = False
        stdout  = ""

        for attempt in range(args.max_retries + 1):
            if attempt:
                console.print(f"\n[yellow]Retry {attempt}/{args.max_retries}[/yellow]")

            rc, stdout, stderr = execute(command)
            console.print(f"[dim]{'─' * 52}[/dim]")

            if rc == 0:
                success = True
                break

            console.print(f"[red]Exit code {rc}[/red]")
            log("exec_failed", command=command, rc=rc, attempt=attempt,
                stderr=stderr[:500])

            if attempt >= args.max_retries:
                console.print("[red]Max retries reached.[/red]")
                break

            # ── Phase 4: Error analysis & fix ────────────────────────────────
            fix_resp = stream(
                [{
                    "role": "user",
                    "content": (
                        f"Task: {task}\n"
                        f"Failed command: {command}\n"
                        f"Exit code: {rc}\n"
                        f"stdout: {stdout[:2000] or '(empty)'}\n"
                        f"stderr: {stderr[:2000] or '(empty)'}\n\n"
                        "Diagnose briefly, then provide a corrected ```bash command."
                    ),
                }],
                "AI (fixing)",
            )
            log("fix_response", text=fix_resp)

            fixed = extract_command(fix_resp)
            if not fixed or fixed == command:
                console.print("[yellow]No alternative command suggested — stopping.[/yellow]")
                break

            command = fixed
            console.print(f"\n[bold]Fixed:[/bold] [cyan]{command}[/cyan]")
            try:
                yn = input("Try fixed command? [Y/n]: ").strip().lower()
                if yn in ("n", "no"):
                    break
            except (EOFError, KeyboardInterrupt):
                break

        # ── Phase 5: Success summary ─────────────────────────────────────────
        if success:
            stream(
                [{
                    "role": "user",
                    "content": (
                        f"Task: {task}\n"
                        f"Command: {command}\n"
                        f"Output (truncated): {stdout[:800] or '(no output)'}\n\n"
                        "Give a 1–2 sentence plain-English summary of what was accomplished."
                    ),
                }],
                "Summary",
            )

    # Shutdown logger
    log_q.put(None)
    console.print("\n[green]Session ended. Goodbye![/green]")


# ============================================================
# SECTION 4 — Argument parsing & entry point
# ============================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AI-Powered Terminal Assistant — Claude Opus 4.6 streaming",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--dry-run",      action="store_true",
                   help="Show command without executing")
    p.add_argument("--max-retries",  type=int, default=3, metavar="N",
                   help="Max error-fix retries")
    p.add_argument("--no-enhance",   action="store_true",
                   help="Skip prompt enhancement phase")
    p.add_argument("--log-file",     metavar="PATH",
                   help="Custom session log file path")
    p.add_argument("--timeout",      type=int, default=120, metavar="SECS",
                   help="Subprocess timeout in seconds")
    p.add_argument("--reconfigure",  action="store_true",
                   help="Re-run first-time setup (including provider selection)")
    p.add_argument("--stream-delay", type=int, default=0, metavar="MS",
                   help="Artificial token render delay in milliseconds")
    p.add_argument("--provider",     choices=["claude", "ollama"], metavar="PROVIDER",
                   help="Override provider for this session (claude or ollama)")
    p.add_argument("--ollama-url",   metavar="URL",
                   help=f"Ollama base URL (default: {DEFAULT_OLLAMA_URL})")
    p.add_argument("--ollama-model", metavar="MODEL",
                   help=f"Ollama model name (default: {DEFAULT_OLLAMA_MODEL})")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg  = load_config()

    # ── Bootstrap if needed ──────────────────────────────────────────────────
    if args.reconfigure or not cfg.get("first_run_complete"):
        if args.reconfigure:
            cfg.pop("first_run_complete", None)
        run_bootstrap()
        cfg = load_config()

    # ── Re-exec inside the assistant venv if we're not already there ─────────
    if not in_venv() and VENV_PYTHON.exists():
        if cfg.get("api_key"):
            os.environ["ANTHROPIC_API_KEY"] = cfg["api_key"]
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)
        # execv never returns on success

    # ── Thread 5 — Context Gatherer (fast path: read persisted profile) ──────
    profile: dict = {}
    if PROFILE_FILE.exists():
        try:
            profile = json.loads(PROFILE_FILE.read_text())
        except json.JSONDecodeError:
            profile = collect_system_profile()
    else:
        profile = collect_system_profile()

    # ── Inject API key into environment ──────────────────────────────────────
    if cfg.get("api_key") and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = cfg["api_key"]

    run_app(args, cfg, profile)


if __name__ == "__main__":
    main()
