from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


NoveltySignal = Literal["not found", "similar work exists", "exact match found"]


class Reference(BaseModel):
    title: str
    url: str | None = None
    venue: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    snippet: str | None = None
    source: str | None = None
    doi: str | None = None


class Domain(BaseModel):
    id: str
    name: str


class DomainCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    system_prompt: str = Field(min_length=10, max_length=8000)


class DomainUpdateRequest(BaseModel):
    system_prompt: str = Field(min_length=10, max_length=8000)


class HypothesisCreateRequest(BaseModel):
    text: str = Field(min_length=5, max_length=4000)
    domain_id: str | None = None


class HypothesisCreateResponse(BaseModel):
    hypothesis_id: str


class LiteratureQcRequest(BaseModel):
    hypothesis_id: str


class Novelty(BaseModel):
    score: float | None = None
    rationale: str | None = None
    references: list[Reference] = Field(default_factory=list)


class LiteratureQcResponse(BaseModel):
    hypothesis_id: str
    novelty: Novelty


class PlanJsonProtocolStep(BaseModel):
    step: int
    description: str
    source_url: str | None = None


class PlanJsonMaterial(BaseModel):
    name: str
    supplier: str | None = None
    catalog_number: str | None = None
    quantity: str | None = None
    unit_cost_usd: float | None = None


class PlanJsonBudgetItem(BaseModel):
    item: str
    cost_usd: float


class PlanJsonTimelinePhase(BaseModel):
    phase: str
    week_start: int
    week_end: int
    owner: str | None = None


class PlanJsonRisk(BaseModel):
    risk: str
    mitigation: str


class PlanContract(BaseModel):
    protocol: list[PlanJsonProtocolStep]
    materials: list[PlanJsonMaterial]
    budget: list[PlanJsonBudgetItem]
    timeline: list[PlanJsonTimelinePhase]
    risks: list[PlanJsonRisk]
    novelty: Novelty


class GeneratePlanRequest(BaseModel):
    hypothesis_id: str


class GeneratePlanResponse(BaseModel):
    plan_id: str
    hypothesis_id: str
    plan: PlanContract
    model_used: str


class SubmitFeedbackRequest(BaseModel):
    plan_id: str
    scientist_id: str | None = None
    field: str = Field(min_length=1, max_length=200)
    original: Any
    corrected: Any
    note: str | None = Field(default=None, max_length=4000)


class SubmitFeedbackResponse(BaseModel):
    feedback_id: str

