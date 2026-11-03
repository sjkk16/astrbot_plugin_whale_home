from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aiosqlite

from .assets import Assets
from .catalog import initial_state
from .migration import load_state
from .models import HomeState


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        self.db: aiosqlite.Connection | None = None

    async def open(self) -> HomeState:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.directory / "home.sqlite3")
        self.db.row_factory = aiosqlite.Row
        try:
            cursor = await self.db.execute("PRAGMA user_version")
            version = (await cursor.fetchone())[0]
            if version not in (0, 1, 2):
                raise RuntimeError("This home database was created by a newer plugin version.")
            cursor = await self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='home'"
            )
            exists = await cursor.fetchone()
            row = None
            if exists:
                cursor = await self.db.execute("SELECT payload FROM home WHERE id=1")
                row = await cursor.fetchone()
            if version and row is None:
                raise ValueError("Existing database is missing its home state")
            state, migrated = load_state(json.loads(row["payload"])) if row else (initial_state(), False)
            # Existing personas (including the previous default) are user-owned.
            # The playful preset is opt-in for existing homes, never a migration.
            if version == 2 and migrated:
                raise ValueError("Database and state versions do not agree")
            if migrated:
                assets = Assets(self.directory / "assets")
                for asset_id in (
                    state.settings.chibi_asset, state.settings.portrait_asset,
                    state.settings.room_asset, *(d.asset_id for d in state.definitions),
                ):
                    assets.validate_reference(asset_id)
                # SQLite online backup includes committed WAL frames. No state writes precede it.
                await self.backup(self.directory / "backups" / f"before-v2-{uuid4().hex}.sqlite3")
            await self.db.execute("PRAGMA journal_mode=WAL")
            await self.db.execute("PRAGMA foreign_keys=ON")
            await self.db.execute("PRAGMA busy_timeout=5000")
            await self.db.execute("BEGIN IMMEDIATE")
            if row:
                cursor = await self.db.execute("SELECT payload FROM home WHERE id=1")
                if (await cursor.fetchone())["payload"] != row["payload"]:
                    raise RuntimeError("Home changed while opening; restart the plugin")
            # Execute DDL individually; executescript would implicitly commit the migration.
            statements = (
                "CREATE TABLE IF NOT EXISTS home (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, details TEXT NOT NULL DEFAULT '{}')",
                "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, role TEXT NOT NULL, source TEXT NOT NULL, text TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, source TEXT NOT NULL, text TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, mode TEXT NOT NULL, created_at TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT 'pending')",
                "CREATE INDEX IF NOT EXISTS calls_day ON calls(day, mode)",
                "CREATE INDEX IF NOT EXISTS messages_source_id ON messages(source, id)",
                "CREATE INDEX IF NOT EXISTS memories_source_id ON memories(source, id)",
                "CREATE TABLE IF NOT EXISTS companion_local (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS skills_local (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS skill_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, call_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, finished_at TEXT, name TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, trigger TEXT NOT NULL, status TEXT NOT NULL, duration_ms INTEGER, error_code TEXT NOT NULL DEFAULT '')",

            )
            for statement in statements:
                await self.db.execute(statement)
            if row is None or migrated:
                await self.save(state)
            if migrated:
                await self.event(datetime.now(timezone.utc).isoformat(), "system",
                                 "已升级为固定夜景房间；原布局已备份，物品转入收纳，自主生活已暂停。")
            await self.db.execute(
                "UPDATE requests SET status='error', error=? WHERE status='pending'",
                ("上次请求因服务重启而中断，未自动重试。",),
            )
            await self.db.execute("UPDATE calls SET outcome='interrupted' WHERE outcome='pending'")
            await self.db.execute("PRAGMA user_version=2")
            commit = asyncio.create_task(self.db.commit())
            try:
                await asyncio.shield(commit)
            except asyncio.CancelledError:
                await commit
                raise
            return state
        except BaseException:
            await self.db.rollback()
            await self.close()
            raise

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None

    async def save(self, state: HomeState) -> None:
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO home(id,payload) VALUES (1,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (state.model_dump_json(),),
        )

    async def rows(self, table: str, limit: int = 100, before: int | None = None) -> list[dict]:
        assert self.db is not None
        if table not in ("events", "messages", "memories", "skill_calls"):
            raise ValueError("unknown table")
        query = f"SELECT * FROM {table}"
        params: list = []
        if before is not None:
            query += " WHERE id < ?"
            params.append(before)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(5000, max(1, limit)))
        cursor = await self.db.execute(query, params)
        rows = [dict(row) for row in await cursor.fetchall()]
        for row in rows:
            if "details" in row:
                row["details"] = json.loads(row["details"])
        return rows

    async def event(self, now: str, kind: str, text: str, details: dict | None = None) -> None:
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO events(created_at,kind,text,details) VALUES(?,?,?,?)",
            (now, kind, text, json.dumps(details or {}, ensure_ascii=False)),
        )

    async def message(self, now: str, role: str, source: str, text: str) -> int:
        assert self.db is not None
        cursor = await self.db.execute(
            "INSERT INTO messages(created_at,role,source,text) VALUES(?,?,?,?)",
            (now, role, source, text),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def memory(self, now: str, source: str, text: str) -> None:
        assert self.db is not None
        if source == "event":
            cursor = await self.db.execute(
                "SELECT id FROM memories WHERE source='event' AND text=?", (text,)
            )
            if await cursor.fetchone():
                return
        await self.db.execute(
            "INSERT INTO memories(created_at,source,text) VALUES(?,?,?)", (now, source, text)
        )
        await self.db.execute(
            "DELETE FROM memories WHERE source='event' AND id NOT IN "
            "(SELECT id FROM memories WHERE source='event' ORDER BY id DESC LIMIT 100)"
        )

    async def usage(self, day: str) -> dict:
        assert self.db is not None
        cursor = await self.db.execute(
            "SELECT mode, COUNT(*) AS count FROM calls WHERE day=? GROUP BY mode", (day,)
        )
        counts = {row["mode"]: row["count"] for row in await cursor.fetchall()}
        return {
            "day": day,
            "autonomy": counts.get("autonomy", 0),
            "chat": counts.get("chat", 0),
            "interaction": counts.get("interaction", 0),
            "proactive": counts.get("proactive", 0),
        }

    async def conversation_context(self) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        """Bounded independent channels; item chatter cannot evict real conversation."""
        assert self.db is not None
        async def query(sql: str, params: tuple = ()) -> list[dict]:
            cursor = await self.db.execute(sql, params)
            return [dict(row) for row in await cursor.fetchall()]
        messages = await query("SELECT * FROM messages WHERE source='chat' AND role IN ('user','assistant') ORDER BY id DESC LIMIT 24")
        interactions = await query("SELECT * FROM messages WHERE source IN ('interaction','autonomy') ORDER BY id DESC LIMIT 8")
        events = await self.rows("events", 12)
        # Explicit user memories always lead the bounded memory budget.
        memories = await query("SELECT * FROM memories WHERE source='user' ORDER BY id DESC LIMIT 24")
        memories += await query("SELECT * FROM memories WHERE source='event' ORDER BY id DESC LIMIT 8")
        return messages, interactions, events, memories

    async def load_companion(self) -> dict:
        assert self.db is not None
        cursor = await self.db.execute("SELECT payload FROM companion_local WHERE id=1")
        row = await cursor.fetchone()
        return json.loads(row["payload"]) if row else {}

    async def save_companion(self, payload: dict) -> None:
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO companion_local(id,payload) VALUES(1,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(payload, ensure_ascii=False),),
        )

    async def backup(self, destination: Path) -> None:
        assert self.db is not None
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(destination) as target:
            await self.db.backup(target)


    async def load_skills(self) -> dict:
        assert self.db is not None
        cursor = await self.db.execute("SELECT payload FROM skills_local WHERE id=1")
        row = await cursor.fetchone()
        return json.loads(row["payload"]) if row else {}

    async def save_skills(self, payload: dict) -> None:
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO skills_local(id,payload) VALUES(1,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(payload, ensure_ascii=False),),
        )
