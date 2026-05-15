import sqlite3
import asyncio
import logging
import os
import hashlib
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("TFFBot.Database")

DB_PATH = "tff_bot.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA secure_delete=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def init_database():
    """Initialize all database tables."""
    conn = get_connection()
    cursor = conn.cursor()

    # ── Guild Settings ──────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id        INTEGER PRIMARY KEY,
            log_channel_id  INTEGER,
            mod_log_id      INTEGER,
            welcome_channel INTEGER,
            goodbye_channel INTEGER,
            verify_channel  INTEGER,
            verified_role   INTEGER,
            muted_role      INTEGER,
            support_role    INTEGER,
            ticket_category INTEGER,
            monitor_channel INTEGER,
            alert_channel   INTEGER,
            transcript_channel INTEGER,
            lockdown_active INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Warnings ────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            mod_id      INTEGER NOT NULL,
            reason      TEXT NOT NULL,
            warned_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id)")

    # ── Mutes ───────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mutes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            mod_id      INTEGER NOT NULL,
            reason      TEXT,
            expires_at  TEXT,
            active      INTEGER DEFAULT 1,
            muted_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mutes_active ON mutes(guild_id, user_id, active)")

    # ── Bans ────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            mod_id      INTEGER NOT NULL,
            reason      TEXT,
            banned_at   TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Tickets ─────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id        INTEGER NOT NULL,
            channel_id      INTEGER UNIQUE NOT NULL,
            user_id         INTEGER NOT NULL,
            ticket_number   INTEGER NOT NULL,
            subject         TEXT,
            status          TEXT DEFAULT 'open',
            claimed_by      INTEGER,
            transcript      TEXT,
            opened_at       TEXT DEFAULT (datetime('now')),
            closed_at       TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_guild ON tickets(guild_id, status)")

    # ── Anti-Spam Tracking ──────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spam_tracker (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            channel_id  INTEGER NOT NULL,
            msg_count   INTEGER DEFAULT 1,
            window_start TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Raid Log ────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            action      TEXT NOT NULL,
            detail      TEXT,
            logged_at   TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Mod Actions Log ─────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mod_actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            mod_id      INTEGER NOT NULL,
            target_id   INTEGER,
            action      TEXT NOT NULL,
            reason      TEXT,
            detail      TEXT,
            executed_at TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mod_actions_guild ON mod_actions(guild_id)")

    # ── Verification ────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            code        TEXT NOT NULL,
            verified    INTEGER DEFAULT 0,
            expires_at  TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Welcome Config ──────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS welcome_config (
            guild_id        INTEGER PRIMARY KEY,
            title           TEXT,
            description     TEXT,
            footer          TEXT,
            image_url       TEXT,
            thumbnail_url   TEXT,
            color           INTEGER,
            enabled         INTEGER DEFAULT 1,
            updated_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Deadline Channels ───────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deadline_channels (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id        INTEGER NOT NULL,
            channel_id      INTEGER NOT NULL,
            role1_id        INTEGER NOT NULL,
            role2_id        INTEGER NOT NULL,
            task_name       TEXT NOT NULL,
            deadline        TEXT NOT NULL,
            message_id      INTEGER,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Security Events ─────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS security_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            event_type  TEXT NOT NULL,
            user_id     INTEGER,
            detail      TEXT,
            severity    TEXT DEFAULT 'low',
            logged_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sec_events_guild ON security_events(guild_id, event_type)")

    conn.commit()
    conn.close()
    logger.info("✅ Database initialized successfully.")


# ── Guild Settings ───────────────────────────────────────────────────────────

def get_guild_settings(guild_id: int) -> Optional[Dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_guild_settings(guild_id: int, **kwargs):
    conn = get_connection()
    existing = conn.execute("SELECT guild_id FROM guild_settings WHERE guild_id = ?", (guild_id,)).fetchone()
    if existing:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [guild_id]
        conn.execute(f"UPDATE guild_settings SET {sets}, updated_at = datetime('now') WHERE guild_id = ?", vals)
    else:
        kwargs["guild_id"] = guild_id
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" * len(kwargs))
        conn.execute(f"INSERT INTO guild_settings ({cols}) VALUES ({placeholders})", list(kwargs.values()))
    conn.commit()
    conn.close()


# ── Warnings ─────────────────────────────────────────────────────────────────

def add_warning(guild_id: int, user_id: int, mod_id: int, reason: str) -> int:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO warnings (guild_id, user_id, mod_id, reason) VALUES (?, ?, ?, ?)",
        (guild_id, user_id, mod_id, reason)
    )
    warn_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return warn_id


def get_warnings(guild_id: int, user_id: int) -> List[Dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY warned_at DESC",
        (guild_id, user_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_warnings(guild_id: int, user_id: int) -> int:
    conn = get_connection()
    cursor = conn.execute("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


# ── Mutes ─────────────────────────────────────────────────────────────────────

def add_mute(guild_id: int, user_id: int, mod_id: int, reason: str, expires_at: Optional[str]) -> int:
    conn = get_connection()
    conn.execute("UPDATE mutes SET active = 0 WHERE guild_id = ? AND user_id = ? AND active = 1", (guild_id, user_id))
    cursor = conn.execute(
        "INSERT INTO mutes (guild_id, user_id, mod_id, reason, expires_at) VALUES (?, ?, ?, ?, ?)",
        (guild_id, user_id, mod_id, reason, expires_at)
    )
    mute_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return mute_id


def remove_mute(guild_id: int, user_id: int):
    conn = get_connection()
    conn.execute("UPDATE mutes SET active = 0 WHERE guild_id = ? AND user_id = ? AND active = 1", (guild_id, user_id))
    conn.commit()
    conn.close()


def get_expired_mutes() -> List[Dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM mutes WHERE active = 1 AND expires_at IS NOT NULL AND expires_at <= datetime('now')"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Mod Actions ───────────────────────────────────────────────────────────────

def log_mod_action(guild_id: int, mod_id: int, action: str, target_id: Optional[int] = None,
                   reason: Optional[str] = None, detail: Optional[str] = None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO mod_actions (guild_id, mod_id, target_id, action, reason, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (guild_id, mod_id, target_id, action, reason, detail)
    )
    conn.commit()
    conn.close()


# ── Tickets ───────────────────────────────────────────────────────────────────

def create_ticket(guild_id: int, channel_id: int, user_id: int, ticket_number: int, subject: Optional[str]) -> int:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO tickets (guild_id, channel_id, user_id, ticket_number, subject) VALUES (?, ?, ?, ?, ?)",
        (guild_id, channel_id, user_id, ticket_number, subject)
    )
    tid = cursor.lastrowid
    conn.commit()
    conn.close()
    return tid


def get_ticket_by_channel(channel_id: int) -> Optional[Dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_open_tickets(guild_id: int, user_id: int) -> List[Dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
        (guild_id, user_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def close_ticket(channel_id: int, transcript: Optional[str] = None):
    conn = get_connection()
    conn.execute(
        "UPDATE tickets SET status = 'closed', closed_at = datetime('now'), transcript = ? WHERE channel_id = ?",
        (transcript, channel_id)
    )
    conn.commit()
    conn.close()


def get_next_ticket_number(guild_id: int) -> int:
    conn = get_connection()
    row = conn.execute("SELECT MAX(ticket_number) as max_num FROM tickets WHERE guild_id = ?", (guild_id,)).fetchone()
    conn.close()
    return (row["max_num"] or 0) + 1


def claim_ticket(channel_id: int, mod_id: int):
    conn = get_connection()
    conn.execute("UPDATE tickets SET claimed_by = ? WHERE channel_id = ?", (mod_id, channel_id))
    conn.commit()
    conn.close()


# ── Verification ──────────────────────────────────────────────────────────────

def create_verification(guild_id: int, user_id: int, code: str, expires_at: str):
    conn = get_connection()
    conn.execute("DELETE FROM verifications WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    conn.execute(
        "INSERT INTO verifications (guild_id, user_id, code, expires_at) VALUES (?, ?, ?, ?)",
        (guild_id, user_id, code, expires_at)
    )
    conn.commit()
    conn.close()


def verify_code(guild_id: int, user_id: int, code: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM verifications WHERE guild_id = ? AND user_id = ? AND code = ? AND verified = 0 AND expires_at > datetime('now')",
        (guild_id, user_id, code)
    ).fetchone()
    if row:
        conn.execute("UPDATE verifications SET verified = 1 WHERE id = ?", (row["id"],))
        conn.commit()
    conn.close()
    return row is not None


# ── Security Events ───────────────────────────────────────────────────────────

def log_security_event(guild_id: int, event_type: str, user_id: Optional[int] = None,
                       detail: Optional[str] = None, severity: str = "low"):
    conn = get_connection()
    conn.execute(
        "INSERT INTO security_events (guild_id, event_type, user_id, detail, severity) VALUES (?, ?, ?, ?, ?)",
        (guild_id, event_type, user_id, detail, severity)
    )
    conn.commit()
    conn.close()


def get_security_events(guild_id: int, limit: int = 50) -> List[Dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM security_events WHERE guild_id = ? ORDER BY logged_at DESC LIMIT ?",
        (guild_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Welcome Config ────────────────────────────────────────────────────────────

def get_welcome_config(guild_id: int) -> Optional[Dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM welcome_config WHERE guild_id = ?", (guild_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_welcome_config(guild_id: int, **kwargs):
    conn = get_connection()
    existing = conn.execute("SELECT guild_id FROM welcome_config WHERE guild_id = ?", (guild_id,)).fetchone()
    if existing:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [guild_id]
        conn.execute(f"UPDATE welcome_config SET {sets}, updated_at = datetime('now') WHERE guild_id = ?", vals)
    else:
        kwargs["guild_id"] = guild_id
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" * len(kwargs))
        conn.execute(f"INSERT INTO welcome_config ({cols}) VALUES ({placeholders})", list(kwargs.values()))
    conn.commit()
    conn.close()


# ── Deadline Channels ─────────────────────────────────────────────────────────

def add_deadline_channel(guild_id: int, channel_id: int, role1_id: int, role2_id: int,
                         task_name: str, deadline: str) -> int:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO deadline_channels (guild_id, channel_id, role1_id, role2_id, task_name, deadline) VALUES (?, ?, ?, ?, ?, ?)",
        (guild_id, channel_id, role1_id, role2_id, task_name, deadline)
    )
    did = cursor.lastrowid
    conn.commit()
    conn.close()
    return did


def get_deadline_channels(guild_id: int) -> List[Dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM deadline_channels WHERE guild_id = ?", (guild_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
