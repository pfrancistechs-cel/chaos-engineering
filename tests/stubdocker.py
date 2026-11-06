#!/usr/bin/env python3
"""A stand-in for the `docker` command, for tests only. It "containers" are plain processes.
State directory: $STUB_STATE. Each container has <name>.json {cmd, env, pid, stopped}.
Supported: kill, pause, unpause, stop, start, info, ps, inspect. `kill` honours a restart policy (restart after 1 s),
like `restart: unless-stopped` does for `docker kill`; `stop` does not restart."""
import json
import os
import signal
import subprocess
import sys
import time

STATE = os.environ["STUB_STATE"]


def path(name):
    return os.path.join(STATE, name + ".json")


def load(name):
    with open(path(name)) as fh:
        return json.load(fh)


def save(name, data):
    with open(path(name), "w") as fh:
        json.dump(data, fh)


def alive(pid):
    try:
        os.kill(pid, 0)
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split(") ")[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def launch(name):
    data = load(name)
    log = open(os.path.join(STATE, name + ".log"), "a")
    proc = subprocess.Popen(data["cmd"], env={**os.environ, **data["env"]}, stdout=log, stderr=log, start_new_session=True)
    data.update(pid=proc.pid, stopped=False)
    save(name, data)


def main(argv):
    cmd = argv[0]
    if cmd in ("info", "ps", "inspect", "version"):
        return 0
    if cmd == "compose":                       # only `docker compose ps -q` is needed (smoke.sh counts containers)
        if "ps" in argv:
            print("\n".join(f"container{i}" for i in range(6)))
        return 0
    if cmd == "_delayed_launch":
        time.sleep(float(argv[2]))
        data = load(argv[1])
        if not data.get("stopped") and not alive(data["pid"]):
            launch(argv[1])
        return 0
    name = argv[1]
    data = load(name)
    if cmd == "kill":
        if alive(data["pid"]):
            os.kill(data["pid"], signal.SIGKILL)
            subprocess.Popen([sys.executable, __file__, "_delayed_launch", name, "1.0"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif cmd == "pause":
        os.kill(data["pid"], signal.SIGSTOP)
    elif cmd == "unpause":
        if alive(data["pid"]):
            os.kill(data["pid"], signal.SIGCONT)
    elif cmd == "stop":
        data["stopped"] = True
        save(name, data)
        if alive(data["pid"]):
            os.kill(data["pid"], signal.SIGTERM)
    elif cmd == "start":
        if not alive(data["pid"]):
            launch(name)
    else:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
