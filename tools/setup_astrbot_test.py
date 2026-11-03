"""Prepare an isolated, loopback-only AstrBot instance; never change the user's instance."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / ".runtime/astrbot/AstrBot-4.29.3"
parser = argparse.ArgumentParser()
parser.add_argument("--instance", type=Path, default=ROOT / ".local/astrbot-v021-test")
parser.add_argument("--port", type=int, default=18763)
parser.add_argument("--empty", action="store_true", help="Do not preinstall a plugin; test ZIP install")
args = parser.parse_args()
INSTANCE = args.instance.resolve()
if not INSTANCE.is_relative_to((ROOT / ".local").resolve()) or INSTANCE == (ROOT / ".local").resolve():
    raise SystemExit("Test instance must be a dedicated child directory of .local")
plugin = INSTANCE / "data/plugins/astrbot_plugin_whale_home"
if args.empty and plugin.exists():
    raise SystemExit("This test instance already has a plugin. Choose a new test directory.")
os.environ["ASTRBOT_ROOT"] = str(INSTANCE)
sys.path.insert(0, str(CORE))

from astrbot.core.config.default import DEFAULT_CONFIG  # noqa: E402
from astrbot.core.utils.auth_password import hash_dashboard_password  # noqa: E402

INSTANCE.mkdir(parents=True, exist_ok=True)
data = INSTANCE / "data"
data.mkdir(exist_ok=True)
credentials_path = INSTANCE / "test-credentials.json"
if credentials_path.exists():
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
else:
    credentials = {"username": "whale-test", "password": f"Whale{secrets.token_urlsafe(24)}9"}
    credentials_path.write_text(json.dumps(credentials), encoding="utf-8")
config = copy.deepcopy(DEFAULT_CONFIG)
config["dashboard"].update({
    "host": "127.0.0.1", "port": args.port, "username": credentials["username"],
    "password": hashlib.md5(credentials["password"].encode()).hexdigest(),
    "pbkdf2_password": hash_dashboard_password(credentials["password"]),
    "password_storage_upgraded": True, "password_change_required": False,
    "jwt_secret": secrets.token_urlsafe(48),
})
config["platform"] = []
config["provider"] = []
config["provider_sources"] = []
config["provider_settings"]["cua_telemetry_enabled"] = False
(data / "cmd_config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
if not args.empty:
    plugin.mkdir(parents=True, exist_ok=True)
    for name in ("main.py", "metadata.yaml", "requirements.txt", "README.md", "LICENSE", "ASSETS.md",
                 "PERSONAL-USE-NOTICE.md", "VERIFICATION.md", "asset-manifest.json"):
        shutil.copy2(ROOT / name, plugin / name)
    for name in ("whale_home", "views", ".astrbot-plugin", "licenses"):
        shutil.copytree(ROOT / name, plugin / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
print(f"Prepared isolated AstrBot 4.29.3 at {INSTANCE.name}, port {args.port}; empty={args.empty}.")
