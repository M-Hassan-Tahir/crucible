from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import HealthResponse, settings
from app.db import (
    create_domain,
    create_hypothesis,
    create_literature_qc,
    create_plan,
    get_domain,
    get_hypothesis,
    get_latest_literature_qc,
    get_plan,
    init_db,
    list_domains,
    list_history,
    list_recent_feedback,
    nearest_feedback,
    submit_feedback,
    update_domain,
)
from app.models import (
    DomainCreateRequest,
    DomainUpdateRequest,
    GeneratePlanRequest,
    GeneratePlanResponse,
    HypothesisCreateRequest,
    HypothesisCreateResponse,
    LiteratureQcRequest,
    LiteratureQcResponse,
    SubmitFeedbackRequest,
    SubmitFeedbackResponse,
    Reference,
)
from app.providers.literature import (
    arxiv_search,
    novelty_score_from_titles,
    semantic_scholar_search,
    tavily_search,
)
from app.providers.llm import generate_plan_openai_compatible


app = FastAPI(title="Crucible API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    await init_db(settings.ai_scientist_db_path)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()

@app.get("/domains")
async def domains() -> dict:
    return {"domains": await list_domains(settings.ai_scientist_db_path)}


@app.post("/domains")
async def create_domain_ep(req: DomainCreateRequest) -> dict:
    domain_id = await create_domain(
        settings.ai_scientist_db_path, req.name.strip(), req.system_prompt.strip()
    )
    return {"id": domain_id, "name": req.name.strip(), "system_prompt": req.system_prompt.strip()}


@app.put("/domains/{domain_id}")
async def update_domain_ep(domain_id: str, req: DomainUpdateRequest) -> dict:
    ok = await update_domain(
        settings.ai_scientist_db_path, domain_id, req.system_prompt.strip()
    )
    if not ok:
        raise HTTPException(status_code=404, detail="domain not found")
    return {"ok": True, "id": domain_id}


@app.get("/feedback")
async def feedback_ep(limit: int = 50) -> dict:
    return {
        "items": await list_recent_feedback(settings.ai_scientist_db_path, limit=limit)
    }


@app.get("/settings")
async def settings_ep() -> dict:
    has_openai = bool(
        settings.openai_api_key and settings.openai_api_key.get_secret_value()
    )
    has_tavily = bool(
        settings.tavily_api_key and settings.tavily_api_key.get_secret_value()
    )
    base_url = settings.openai_base_url or "https://api.openai.com/v1"
    try:
        from urllib.parse import urlparse

        provider_host = urlparse(base_url).netloc or base_url
    except Exception:
        provider_host = base_url
    return {
        "openai_model": settings.openai_model,
        "openai_base_url": base_url,
        "provider_host": provider_host,
        "openai_api_key_set": has_openai,
        "tavily_api_key_set": has_tavily,
        "db_path": settings.ai_scientist_db_path,
    }


@app.post("/hypotheses", response_model=HypothesisCreateResponse)
async def create(req: HypothesisCreateRequest) -> HypothesisCreateResponse:
    if req.domain_id:
        d = await get_domain(settings.ai_scientist_db_path, req.domain_id)
        if d is None:
            raise HTTPException(status_code=400, detail="domain_id not found")
    hypothesis_id = await create_hypothesis(settings.ai_scientist_db_path, req.text, req.domain_id, user_id=None)
    return HypothesisCreateResponse(hypothesis_id=hypothesis_id)


@app.post("/literature-qc", response_model=LiteratureQcResponse)
async def literature_qc(req: LiteratureQcRequest) -> LiteratureQcResponse:
    import asyncio

    hyp = await get_hypothesis(settings.ai_scientist_db_path, req.hypothesis_id)
    if hyp is None:
        raise HTTPException(status_code=404, detail="hypothesis not found")

    tavily_key = (
        settings.tavily_api_key.get_secret_value()
        if settings.tavily_api_key is not None
        else ""
    )

    ss_refs, ax_refs, tv_refs = await asyncio.gather(
        semantic_scholar_search(hyp["text"], limit=12),
        arxiv_search(hyp["text"], limit=12),
        tavily_search(hyp["text"], tavily_key, limit=6) if tavily_key else asyncio.sleep(0, result=[]),
    )

    def _key(r) -> str:
        return (r.url or r.title or "").strip().lower()

    # Build a mixed, deduped list: up to 3 web (Tavily) + up to 8 research papers
    # (Semantic Scholar preferred, arXiv as fallback) so the user always sees both kinds.
    WEB_TARGET = 3
    PAPER_TARGET = 8

    web_top: list = []
    seen: set[str] = set()
    for r in tv_refs or []:
        k = _key(r)
        if k and k not in seen:
            seen.add(k)
            web_top.append(r)
        if len(web_top) >= WEB_TARGET:
            break

    # Interleave Semantic Scholar and arXiv so the user sees a mix of both sources
    # rather than all of one before any of the other.
    interleaved: list = []
    ss_iter = iter(ss_refs or [])
    ax_iter = iter(ax_refs or [])
    exhausted_ss = exhausted_ax = False
    while not (exhausted_ss and exhausted_ax):
        try:
            interleaved.append(next(ss_iter))
        except StopIteration:
            exhausted_ss = True
        try:
            interleaved.append(next(ax_iter))
        except StopIteration:
            exhausted_ax = True

    papers_top: list = []
    for r in interleaved:
        k = _key(r)
        if k and k not in seen:
            seen.add(k)
            papers_top.append(r)
        if len(papers_top) >= PAPER_TARGET:
            break

    primary = web_top + papers_top  # shown in UI

    # Keep any leftover refs around for broader novelty scoring coverage.
    extra: list = []
    for r in (tv_refs or []) + (ss_refs or []) + (ax_refs or []):
        k = _key(r)
        if k and k not in seen:
            seen.add(k)
            extra.append(r)

    all_refs = (primary + extra)[:20]
    score, rationale = novelty_score_from_titles(hyp["text"], all_refs)
    provider_hint = (
        "Tavily + Semantic Scholar + arXiv" if tavily_key else "Semantic Scholar + arXiv"
    )
    summary = f"Novelty estimated from {provider_hint}. {rationale}"

    await create_literature_qc(
        settings.ai_scientist_db_path,
        hypothesis_id=req.hypothesis_id,
        novelty_score=score,
        summary=summary,
        references=[r.model_dump() for r in primary],
    )

    return LiteratureQcResponse(
        hypothesis_id=req.hypothesis_id,
        novelty={"score": score, "rationale": rationale, "references": primary},
    )


@app.post("/generate-plan", response_model=GeneratePlanResponse)
async def generate_plan(req: GeneratePlanRequest) -> GeneratePlanResponse:
    hyp = await get_hypothesis(settings.ai_scientist_db_path, req.hypothesis_id)
    if hyp is None:
        raise HTTPException(status_code=404, detail="hypothesis not found")

    qc = await get_latest_literature_qc(settings.ai_scientist_db_path, req.hypothesis_id)
    if qc is None:
        raise HTTPException(status_code=400, detail="Run literature QC before generating a plan.")

    if not settings.openai_api_key or not settings.openai_api_key.get_secret_value():
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not set. Set it to enable plan generation.",
        )

    base_url = settings.openai_base_url or "https://api.openai.com/v1"
    api_key = settings.openai_api_key.get_secret_value()

    domain_system_prompt = None
    if hyp.get("domain_id"):
        d = await get_domain(settings.ai_scientist_db_path, hyp["domain_id"])
        domain_system_prompt = d["system_prompt"] if d else None

    refs = [Reference.model_validate(r) for r in (qc.get("references") or [])]
    fewshots = await nearest_feedback(
        settings.ai_scientist_db_path,
        hypothesis_text=hyp["text"],
        domain_id=hyp.get("domain_id"),
        k=3,
    )

    try:
        plan_contract = await generate_plan_openai_compatible(
            base_url=base_url,
            api_key=api_key,
            model=settings.openai_model,
            hypothesis_text=hyp["text"],
            domain_system_prompt=domain_system_prompt,
            novelty={
                "score": qc.get("novelty_score"),
                "rationale": qc.get("summary"),
                "references": [r.model_dump() for r in refs],
            },
            references=refs,
            feedback_items=fewshots,
        )
    except httpx.HTTPStatusError as e:
        # Return upstream error text to help debug auth/model issues.
        raise HTTPException(
            status_code=502,
            detail=f"LLM request failed ({e.response.status_code}): {e.response.text}",
        ) from e

    plan_id = await create_plan(
        settings.ai_scientist_db_path,
        hypothesis_id=req.hypothesis_id,
        protocol=[x.model_dump() for x in plan_contract.protocol],
        materials=[x.model_dump() for x in plan_contract.materials],
        budget=[x.model_dump() for x in plan_contract.budget],
        timeline=[x.model_dump() for x in plan_contract.timeline],
        risks=[x.model_dump() for x in plan_contract.risks],
        model_used=settings.openai_model,
    )

    return GeneratePlanResponse(
        plan_id=plan_id,
        hypothesis_id=req.hypothesis_id,
        plan=plan_contract,
        model_used=settings.openai_model,
    )


@app.get("/plans/{plan_id}")
async def read_plan(plan_id: str) -> dict:
    plan = await get_plan(settings.ai_scientist_db_path, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    qc = await get_latest_literature_qc(settings.ai_scientist_db_path, plan["hypothesis_id"])
    hyp = await get_hypothesis(settings.ai_scientist_db_path, plan["hypothesis_id"])
    return {"plan": plan, "hypothesis": hyp, "literature_qc": qc}


@app.get("/history")
async def history() -> dict:
    return {"items": await list_history(settings.ai_scientist_db_path, limit=50)}


@app.post("/submit-feedback", response_model=SubmitFeedbackResponse)
async def submit(req: SubmitFeedbackRequest) -> SubmitFeedbackResponse:
    plan = await get_plan(settings.ai_scientist_db_path, req.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    fid = await submit_feedback(
        settings.ai_scientist_db_path,
        plan_id=req.plan_id,
        scientist_id=req.scientist_id,
        field=req.field,
        original=req.original,
        corrected=req.corrected,
        note=req.note,
    )
    return SubmitFeedbackResponse(feedback_id=fid)

