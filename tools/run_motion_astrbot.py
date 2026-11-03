"""Run only a prepared, model-free AstrBot test instance with loopback networking.

This process-only guard is for offline verification, not a production security sandbox.
It does not edit AstrBot's installation, user configuration, or system firewall.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import runpy
import site
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True, type=Path)
    args = parser.parse_args()
    instance = args.instance.resolve()
    local = (ROOT / ".local").resolve()
    if not instance.is_relative_to(local) or instance == local:
        raise SystemExit("Use a dedicated prepared .local test instance")
    config = json.loads((instance / "data/cmd_config.json").read_text(encoding="utf-8-sig"))
    credentials = json.loads((instance / "test-credentials.json").read_text(encoding="utf-8-sig"))
    if (config["dashboard"]["host"] != "127.0.0.1" or config["provider"]
            or config["provider_sources"] or config["platform"]
            or credentials["username"] != "whale-test"):
        raise SystemExit("Refusing a non-isolated or provider-enabled instance")
    core = ROOT / ".runtime/astrbot/AstrBot-4.29.3"
    site.addsitedir(str(core / ".venv/Lib/site-packages"))
    dashboard = ROOT / ".runtime/astrbot-dashboard/dist"
    if not (dashboard / "index.html").is_file():
        raise SystemExit("Offline dashboard assets are required")

    def offline(event, values):
        address = None
        if event in {"socket.connect", "socket.bind"} and isinstance(values[1], tuple):
            address = values[1][0]
        elif event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            address = values[0]
        if address is None or address == "localhost":
            return
        try:
            if ipaddress.ip_address(address).is_loopback:
                return
        except ValueError:
            pass
        raise OSError("Offline verification blocks non-loopback network access")

    os.environ["ASTRBOT_ROOT"] = str(instance)
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.addaudithook(offline)
    sys.path.insert(0, str(core))
    os.chdir(instance)
    sys.argv = [str(core / "main.py"), "--webui-dir", str(dashboard)]
    runpy.run_path(str(core / "main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
