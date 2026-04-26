from __future__ import annotations

import json
from typing import Any

import httpx

from app.models import PlanContract, Reference


PLAN_CONTRACT_HELP = """You are an expert principal investigator writing a
grant-quality experimental plan. Return ONLY valid JSON matching this contract
(no prose outside JSON):

{
  "protocol":  [{ "step": 1, "description": "...", "source_url": "..." }],
  "materials": [{ "name": "...", "supplier": "Sigma-Aldrich", "catalog_number": "...", "quantity": "...", "unit_cost_usd": 0 }],
  "budget":    [{ "item": "...", "cost_usd": 0 }],
  "timeline":  [{ "phase": "...", "week_start": 1, "week_end": 2, "owner": "..." }],
  "risks":     [{ "risk": "...", "mitigation": "..." }],
  "novelty":   { "score": 0.0, "rationale": "...", "references": [] }
}

MINIMUM RICHNESS (hard requirements):
- protocol: AT LEAST 10 steps. Each "description" must be 2-4 full sentences
  covering: reagent concentrations, volumes, temperatures, durations,
  instrument settings, replicates, controls, and QC checkpoints. Do NOT use
  one-line placeholders. Include positive/negative controls as explicit steps.
- materials: AT LEAST 8 items. Include reagents, consumables, instrument
  time, software, and reference standards. Provide realistic supplier +
  catalog_number when plausible; otherwise null. Quantities must be specific
  (e.g. "500 mL, 99.9% purity").
- budget: AT LEAST 6 line items totaling a realistic amount (reagents,
  consumables, instrument time, personnel, publication / data storage, etc.).
- timeline: AT LEAST 5 phases spanning the full project (planning,
  procurement, pilot, main experiment, analysis, writeup). Use week numbers
  and assign owners (role names are fine).
- risks: AT LEAST 5 technical/operational/safety risks with concrete,
  actionable mitigations (not generic advice).

STYLE:
- Be domain-specific. Avoid vague language like "conduct the experiment".
- Where possible cite URLs from the provided references in "source_url".
- Honor any "prior_feedback" corrections and propagate their intent.
"""


def _feedback_to_fewshot(feedback_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not feedback_items:
        return []
    out: list[dict[str, Any]] = []
    for f in feedback_items[:6]:
        out.append(
            {
                "field": f.get("field"),
                "original": f.get("original"),
                "corrected": f.get("corrected"),
                "note": f.get("note"),
                "score": f.get("score"),
            }
        )
    return out


async def generate_plan_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    hypothesis_text: str,
    domain_system_prompt: str | None,
    novelty: dict[str, Any],
    references: list[Reference],
    feedback_items: list[dict[str, Any]],
) -> PlanContract:
    fewshot = _feedback_to_fewshot(feedback_items)
    system = (
        (domain_system_prompt or "You are a principal investigator and lab operations scientist. "
         "Write thorough, grant-quality experimental plans with concrete, actionable detail.")
        + "\n\n"
        + PLAN_CONTRACT_HELP
    )
    user_prompt = {
        "hypothesis": hypothesis_text,
        "novelty": novelty,
        "references": [r.model_dump() for r in references],
        "prior_feedback": fewshot,
        "requirements": [
            "Make this plan operationally realistic for a real lab.",
            "Be exhaustive: do not truncate or summarize.",
            "Protocol steps must be long-form (2-4 sentences each) with explicit volumes, concentrations, temperatures, times, instrument settings, and controls.",
            "Every section must meet the MINIMUM RICHNESS counts in the system prompt.",
            "Include at least one negative and one positive control step.",
            "Materials must include reagents, consumables, instrument time, and software.",
            "Budget line items should cover reagents, consumables, instrument time, personnel, and publication/data storage.",
            "Timeline must cover planning, procurement, pilot, main experiment, analysis, and writeup phases.",
            "Risks must be domain-specific (technical + operational + safety) with concrete mitigations.",
            "Prefer catalog_number / supplier grounded in the provided references when plausible; else null.",
            "Cite the provided reference URLs in 'source_url' where relevant.",
        ],
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_prompt)},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        # OpenRouter attribution headers (ignored by other OpenAI-compatible hosts).
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "Crucible",
    }
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers
        )
        r.raise_for_status()
        data = r.json()

    content = data["choices"][0]["message"]["content"]
    obj = json.loads(content)

    # Some models (e.g. gpt-oss-120b) simplify `novelty.references` to bare URL
    # strings or drop fields; our schema expects full Reference objects. The
    # server already has the authoritative novelty, so overwrite whatever the
    # model emitted for that field and normalize any stragglers.
    obj["novelty"] = {
        "score": novelty.get("score"),
        "rationale": novelty.get("rationale") or "",
        "references": _normalize_refs(novelty.get("references") or []),
    }

    return PlanContract.model_validate(obj)


def _normalize_refs(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            out.append(it)
        elif isinstance(it, str):
            looks_like_url = it.startswith("http://") or it.startswith("https://")
            out.append(
                {
                    "title": it if not looks_like_url else it.rsplit("/", 1)[-1] or it,
                    "url": it if looks_like_url else None,
                }
            )
    return out

