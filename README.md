# folder_syncer

A lightweight daemon that keeps a local directory in sync with Redis.  
On boot it restores any files cached in Redis to disk; at runtime it watches
the directory for changes and mirrors them back to Redis.

---

## How it works

| Phase | What happens |
|---|---|
| **Boot restore** | Reads all keys under `REDIS_KEY_PREFIX` and writes missing / outdated files to disk |
| **Live watch** | Uses [watchdog](https://github.com/gorakhargosh/watchdog) to detect create / modify / delete events and updates Redis accordingly |

File content is stored base64-encoded inside a Redis hash together with the
file name, byte size, and modification time.

---

## Requirements

- Python 3.11+
- A reachable Redis instance

Install dependencies:

```bash
pip install redis watchdog pydantic-settings
```

---

## Configuration

All settings are read from environment variables (or a `.env` file in the
project root).  Copy `.env.example` to `.env` and edit as needed.

| Variable | Default | Description |
|---|---|---|
| `WATCH_DIR` | `data` | Local directory to watch and restore into |
| `REDIS_HOST` | `localhost` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_KEY_PREFIX` | `file_cache:` | Namespace prefix for Redis keys |
| `PID_FILE` | `/tmp/folder_syncer.pid` | PID file used for daemon management |
| `LOG_FILE` | `/tmp/folder_syncer.log` | Log output path |

---

## Usage

```bash
# Start as a background daemon
python main.py start

# Start in the foreground (handy for Docker or debugging)
python main.py start --fg

# Check daemon status
python main.py status

# Stop the daemon
python main.py stop
```

---

## Project structure

```
folder_syncer/
├── main.py        # Entry point – daemon lifecycle + sync logic
├── settings.py    # Pydantic settings model (reads .env)
├── .env.example   # Template for environment configuration
└── README.md
```

---

## Notes

- The boot restore uses **file size** as a quick equality check. If a file
  differs in size from the cached version it is overwritten; otherwise it is
  left untouched to avoid unnecessary disk writes.
- The daemon uses a **double-fork** strategy so it fully detaches from the
  terminal. Logs are written to `LOG_FILE` even after the TTY is gone.
- On `SIGTERM` or `SIGINT` the observer is stopped gracefully and the PID
  file is cleaned up.
