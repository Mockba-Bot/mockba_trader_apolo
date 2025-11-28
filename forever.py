import subprocess
import time
import sys
import os
from datetime import datetime

# List of scripts to run (relative to project root)
scripts = [
    # apolo futures perp scalping bot
    "futures_perps/trade/apolo/main.py",
    # Telegram bot for user interaction
    "telegram.py",
]

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")
    sys.stdout.flush()  # Ensure logs appear in real-time (e.g., in Docker)

def run_script(script_path):
    """Start a script as a subprocess."""
    log(f"🚀 Starting {script_path}")
    # Use 'python' instead of 'python3' for broader compatibility
    return subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1  # Line-buffered
    )

def main():
    processes = {}

    # Start all scripts
    for script in scripts:
        if not os.path.exists(script):
            log(f"❌ Script not found: {script} — skipping!")
            continue
        processes[script] = run_script(script)

    log(f"✅ Supervisor started with {len(processes)} bots.")

    try:
        while True:
            for script, proc in list(processes.items()):
                if proc.poll() is not None:  # Process exited
                    return_code = proc.returncode
                    log(f"⚠️ {script} exited with code {return_code}. Restarting in 3s...")
                    
                    # Optional: read last few lines of output for debugging
                    try:
                        output = proc.stdout.read() if proc.stdout else ""
                        if output:
                            last_lines = output.strip().split('\n')[-3:]
                            for line in last_lines:
                                log(f"   [LOG] {line}")
                    except Exception as e:
                        log(f"   Failed to read logs: {e}")

                    time.sleep(3)
                    processes[script] = run_script(script)

            time.sleep(3)  # Check every 3 seconds

    except KeyboardInterrupt:
        log("🛑 Received SIGINT. Shutting down all bots...")
        for proc in processes.values():
            proc.terminate()
        for proc in processes.values():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        log("✅ All bots stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()