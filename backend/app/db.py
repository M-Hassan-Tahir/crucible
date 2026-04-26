from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite


def _uuid() -> str:
    import uuid

    return str(uuid.uuid4())


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS domains (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  system_prompt TEXT NOT NULL,
  embedding_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hypotheses (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  text TEXT NOT NULL,
  domain_id TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS literature_qc (
  id TEXT PRIMARY KEY,
  hypothesis_id TEXT NOT NULL,
  novelty_score REAL,
  summary TEXT,
  references_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(id)
);

CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY,
  hypothesis_id TEXT NOT NULL,
  protocol_json TEXT NOT NULL,
  materials_json TEXT NOT NULL,
  budget_json TEXT NOT NULL,
  timeline_json TEXT NOT NULL,
  risks_json TEXT NOT NULL,
  model_used TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(id)
);

CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL,
  scientist_id TEXT,
  field TEXT NOT NULL,
  original_json TEXT NOT NULL,
  corrected_json TEXT NOT NULL,
  note TEXT,
  embedding_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(plan_id) REFERENCES plans(id)
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_id TEXT PRIMARY KEY,
  role TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        await db.commit()

        # Seed starter domains if empty (roadmap: 3–5 starter domains).
        cur = await db.execute("SELECT COUNT(*) FROM domains")
        row = await cur.fetchone()
        if int(row[0] if row else 0) == 0:
            seeds = [
                (
                    "Biology",
                    "You are a biology lab operations scientist. Produce protocols, materials, budget, timeline, and validation suitable for wet-lab biology.",
                ),
                (
                    "Chemistry",
                    "You are a chemistry lab operations scientist. Produce protocols, materials, budget, timeline, and validation suitable for chemistry labs.",
                ),
                (
                    "Machine Learning",
                    "You are an ML research engineer. Produce runnable experiment plans including datasets, compute budget, evaluation metrics, and timeline.",
                ),
                (
                    "Materials",
                    "You are a materials science lab operations scientist. Produce protocols and characterization steps for materials experiments.",
                ),
            ]
            for name, prompt in seeds:
                await db.execute(
                    "INSERT INTO domains (id, name, system_prompt, embedding_json, created_at) VALUES (?, ?, ?, NULL, ?)",
                    (_uuid(), name, prompt, _now_iso()),
                )
            await db.commit()

async def list_domains(db_path: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id, name, system_prompt FROM domains ORDER BY name ASC")
        rows = await cur.fetchall()
        return [{"id": r["id"], "name": r["name"], "system_prompt": r["system_prompt"]} for r in rows]


async def get_domain(db_path: str, domain_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id, name, system_prompt FROM domains WHERE id = ?", (domain_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_domain(db_path: str, name: str, system_prompt: str) -> str:
    domain_id = _uuid()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO domains (id, name, system_prompt, embedding_json, created_at) VALUES (?, ?, ?, NULL, ?)",
            (domain_id, name, system_prompt, _now_iso()),
        )
        await db.commit()
    return domain_id


async def update_domain(db_path: str, domain_id: str, system_prompt: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE domains SET system_prompt = ? WHERE id = ?",
            (system_prompt, domain_id),
        )
        await db.commit()
        return (cur.rowcount or 0) > 0


async def create_hypothesis(db_path: str, text: str, domain_id: str | None, user_id: str | None = None) -> str:
    hypothesis_id = _uuid()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO hypotheses (id, user_id, text, domain_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (hypothesis_id, user_id, text, domain_id, "created", _now_iso()),
        )
        await db.commit()
    return hypothesis_id


async def get_hypothesis(db_path: str, hypothesis_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM hypotheses WHERE id = ?", (hypothesis_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_literature_qc(
    db_path: str,
    hypothesis_id: str,
    novelty_score: float | None,
    summary: str | None,
    references: list[dict[str, Any]],
) -> str:
    qc_id = _uuid()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO literature_qc (id, hypothesis_id, novelty_score, summary, references_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (qc_id, hypothesis_id, novelty_score, summary, json.dumps(references), _now_iso()),
        )
        await db.execute("UPDATE hypotheses SET status = ? WHERE id = ?", ("qc_done", hypothesis_id))
        await db.commit()
    return qc_id


async def get_latest_literature_qc(db_path: str, hypothesis_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM literature_qc WHERE hypothesis_id = ? ORDER BY created_at DESC LIMIT 1",
            (hypothesis_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        obj = dict(row)
        obj["references"] = json.loads(obj["references_json"])
        return obj


async def create_plan(
    db_path: str,
    hypothesis_id: str,
    protocol: list[dict[str, Any]],
    materials: list[dict[str, Any]],
    budget: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    model_used: str,
) -> str:
    plan_id = _uuid()
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT COUNT(*) FROM plans WHERE hypothesis_id = ?", (hypothesis_id,))
        row = await cur.fetchone()
        version = int(row[0] if row else 0) + 1
        await db.execute(
            """
            INSERT INTO plans (id, hypothesis_id, protocol_json, materials_json, budget_json, timeline_json, risks_json,
                               model_used, version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                hypothesis_id,
                json.dumps(protocol),
                json.dumps(materials),
                json.dumps(budget),
                json.dumps(timeline),
                json.dumps(risks),
                model_used,
                version,
                _now_iso(),
            ),
        )
        await db.execute("UPDATE hypotheses SET status = ? WHERE id = ?", ("planned", hypothesis_id))
        await db.commit()
    return plan_id


async def get_plan(db_path: str, plan_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
        row = await cur.fetchone()
        if not row:
            return None
        obj = dict(row)
        obj["protocol"] = json.loads(obj["protocol_json"])
        obj["materials"] = json.loads(obj["materials_json"])
        obj["budget"] = json.loads(obj["budget_json"])
        obj["timeline"] = json.loads(obj["timeline_json"])
        obj["risks"] = json.loads(obj["risks_json"])
        return obj


async def list_history(db_path: str, limit: int = 50) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT p.id AS plan_id, p.created_at AS created_at, h.text AS hypothesis_text,
                   d.name AS domain_name, p.version AS version
            FROM plans p
            JOIN hypotheses h ON h.id = p.hypothesis_id
            LEFT JOIN domains d ON d.id = h.domain_id
            ORDER BY p.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


def _embed_text(text: str) -> dict[str, float]:
    import math
    import re

    tokens = [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2]
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    norm = math.sqrt(sum(v * v for v in tf.values())) or 1.0
    return {k: v / norm for k, v in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return float(sum(v * b.get(k, 0.0) for k, v in a.items()))


async def submit_feedback(
    db_path: str,
    *,
    plan_id: str,
    scientist_id: str | None,
    field: str,
    original: Any,
    corrected: Any,
    note: str | None,
) -> str:
    feedback_id = _uuid()
    emb = _embed_text(json.dumps({"field": field, "original": original, "corrected": corrected, "note": note or ""}))
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO feedback (id, plan_id, scientist_id, field, original_json, corrected_json, note, embedding_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (feedback_id, plan_id, scientist_id, field, json.dumps(original), json.dumps(corrected), note, json.dumps(emb), _now_iso()),
        )
        await db.commit()
    return feedback_id


async def list_recent_feedback(db_path: str, limit: int = 50) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT f.id AS id,
                   f.plan_id AS plan_id,
                   f.field AS field,
                   f.original_json AS original_json,
                   f.corrected_json AS corrected_json,
                   f.note AS note,
                   f.created_at AS created_at,
                   h.text AS hypothesis_text,
                   d.name AS domain_name
            FROM feedback f
            JOIN plans p ON p.id = f.plan_id
            JOIN hypotheses h ON h.id = p.hypothesis_id
            LEFT JOIN domains d ON d.id = h.domain_id
            ORDER BY f.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            obj = dict(r)
            try:
                obj["original"] = json.loads(obj.pop("original_json"))
            except Exception:
                obj["original"] = None
                obj.pop("original_json", None)
            try:
                obj["corrected"] = json.loads(obj.pop("corrected_json"))
            except Exception:
                obj["corrected"] = None
                obj.pop("corrected_json", None)
            out.append(obj)
        return out


async def nearest_feedback(
    db_path: str,
    *,
    hypothesis_text: str,
    domain_id: str | None,
    k: int = 3,
) -> list[dict[str, Any]]:
    query = _embed_text(hypothesis_text + (f" domain:{domain_id}" if domain_id else ""))
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT f.* FROM feedback f
            JOIN plans p ON p.id = f.plan_id
            JOIN hypotheses h ON h.id = p.hypothesis_id
            WHERE (? IS NULL) OR (h.domain_id = ?)
            ORDER BY f.created_at DESC
            LIMIT 200
            """,
            (domain_id, domain_id),
        )
        rows = await cur.fetchall()

    scored: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        emb = json.loads(r["embedding_json"]) if r["embedding_json"] else {}
        score = _cosine(query, emb)
        obj = dict(r)
        obj["original"] = json.loads(obj["original_json"])
        obj["corrected"] = json.loads(obj["corrected_json"])
        obj["score"] = score
        scored.append((score, obj))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [o for _, o in scored[:k]]

