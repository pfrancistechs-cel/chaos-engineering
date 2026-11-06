"""Test helper: runs the whole stack as local processes (real nginx as the gateway) with a stub `docker`."""
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NGINX = shutil.which("nginx") or "/usr/sbin/nginx"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Stack:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="chaos")
        os.chmod(self.tmp, 0o755)
        self.state = os.path.join(self.tmp, "state")
        self.config = os.path.join(self.tmp, "config")
        self.results = os.path.join(self.tmp, "results")
        for d in (self.state, self.config, self.results):
            os.makedirs(d)
        with open(os.path.join(self.config, "mode"), "w") as fh:
            fh.write("naive\n")
        self.ports = {k: free_port() for k in ("inventory", "data", "control", "shop1", "shop2", "gateway", "console")}
        self.nginx = None
        py = sys.executable
        demo = os.path.join(ROOT, "demo")
        self.stubdir = os.path.join(self.tmp, "bin")
        os.makedirs(self.stubdir)
        stub = os.path.join(self.stubdir, "docker")
        with open(stub, "w") as fh:
            fh.write(f'#!/usr/bin/env bash\nexec "{py}" "{os.path.join(ROOT, "tests", "stubdocker.py")}" "$@"\n')
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)
        self.env = dict(os.environ, STUB_STATE=self.state, PYTHONUNBUFFERED="1", no_proxy="127.0.0.1", NO_PROXY="127.0.0.1")
        p = self.ports
        mode_file = os.path.join(self.config, "mode")
        self.register("chaos-inventory", [py, f"{demo}/inventory.py"], {"PORT": str(p["inventory"])})
        self.register("chaos-proxy", [py, f"{demo}/chaosproxy.py"],
                      {"UPSTREAM": f"http://127.0.0.1:{p['inventory']}", "DATA_PORT": str(p["data"]),
                       "CONTROL_PORT": str(p["control"]), "BLACKHOLE_SECONDS": "30"})
        for n in ("shop1", "shop2"):
            self.register(f"chaos-{n}", [py, f"{demo}/shop.py"],
                          {"PORT": str(p[n]), "INVENTORY_URL": f"http://127.0.0.1:{p['data']}", "MODE_FILE": mode_file, "SHOP_NAME": n})
        self.register("chaos-console", [py, f"{demo}/console.py"],
                      {"PORT": str(p["console"]), "GATEWAY_URL": f"http://127.0.0.1:{p['gateway']}",
                       "PROXY_STATE_URL": f"http://127.0.0.1:{p['control']}/state", "MODE_FILE": mode_file,
                       "RESULT_FILE": os.path.join(self.results, "last.json")})

    def register(self, name, cmd, env):
        with open(os.path.join(self.state, name + ".json"), "w") as fh:
            json.dump({"cmd": cmd, "env": env, "pid": 0, "stopped": False}, fh)
        subprocess.run([sys.executable, os.path.join(ROOT, "tests", "stubdocker.py"), "start", name], env=self.env, check=True)

    def start_gateway(self):
        with open(os.path.join(ROOT, "gateway", "default.conf")) as fh:
            conf = fh.read().replace("172.29.0.11:8000", f"127.0.0.1:{self.ports['shop1']}") \
                            .replace("172.29.0.12:8000", f"127.0.0.1:{self.ports['shop2']}") \
                            .replace("listen 80;", f"listen 127.0.0.1:{self.ports['gateway']};")
        prefix = os.path.join(self.tmp, "nginx")
        os.makedirs(prefix)
        with open(os.path.join(prefix, "default.conf"), "w") as fh:
            fh.write(conf)
        main = os.path.join(prefix, "nginx.conf")
        with open(main, "w") as fh:
            fh.write(f"pid {prefix}/nginx.pid;\nerror_log {prefix}/error.log warn;\nevents {{ worker_connections 256; }}\n"
                     f"http {{ access_log off; include {prefix}/default.conf; }}\n")
        self.nginx = subprocess.Popen([NGINX, "-p", prefix, "-c", main, "-g", "daemon off;"], env=self.env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def wait_ready(self, secs=30):
        urls = [f"http://127.0.0.1:{self.ports['gateway']}/healthz", f"http://127.0.0.1:{self.ports['control']}/state",
                f"http://127.0.0.1:{self.ports['console']}/healthz", f"http://127.0.0.1:{self.ports['shop1']}/healthz",
                f"http://127.0.0.1:{self.ports['shop2']}/healthz"]
        end = time.time() + secs
        for url in urls:
            while True:
                try:
                    OPENER.open(url, timeout=2).read()
                    break
                except Exception:
                    if time.time() > end:
                        raise RuntimeError(f"not ready: {url}")
                    time.sleep(0.3)

    def start(self):
        self.start_gateway()
        self.wait_ready()
        return self

    def runner_env(self, **extra):
        p = self.ports
        env = dict(self.env, PATH=self.stubdir + os.pathsep + os.environ["PATH"],
                   GATEWAY_URL=f"http://127.0.0.1:{p['gateway']}", PROXY_URL=f"http://127.0.0.1:{p['control']}",
                   CONFIG_DIR=self.config, RESULTS_DIR=self.results, DOCKER_CMD=os.path.join(self.stubdir, "docker"),
                   CONSOLE_URL=f"http://127.0.0.1:{p['console']}")
        env.update(extra)
        return env

    def stop(self):
        import signal
        for fn in sorted(os.listdir(self.state)):
            if fn.endswith(".json"):
                with open(os.path.join(self.state, fn)) as fh:
                    data = json.load(fh)
                data["stopped"] = True
                with open(os.path.join(self.state, fn), "w") as fh:
                    json.dump(data, fh)
                for sig in (signal.SIGCONT, signal.SIGKILL):
                    try:
                        os.kill(data["pid"], sig)
                    except OSError:
                        pass
        if self.nginx:
            try:
                os.killpg(self.nginx.pid, signal.SIGKILL)
            except OSError:
                pass
            self.nginx.wait(timeout=10)
        shutil.rmtree(self.tmp, ignore_errors=True)
