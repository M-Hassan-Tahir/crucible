import { useEffect, useMemo, useState } from 'react'
import './App.css'

type Reference = {
  title: string
  url?: string | null
  venue?: string | null
  year?: number | null
  authors?: string[]
  snippet?: string | null
  source?: string | null
  doi?: string | null
}

type Domain = { id: string; name: string; system_prompt?: string }

const DOMAIN_STARTERS: Record<string, { caption: string; examples: string[] }> = {
  Biology: {
    caption: 'Wet-lab biology protocols — reagents, controls, replicates.',
    examples: [
      'Does rapamycin extend replicative lifespan in S. cerevisiae via TOR inhibition?',
      'Can CRISPR-Cas9 editing of DREB transcription factors enhance drought tolerance in wheat?',
      'Does intermittent fasting reduce hippocampal neuroinflammation in aged mice?',
    ],
  },
  Chemistry: {
    caption: 'Synthesis & characterization — stoichiometry, yields, spectroscopy.',
    examples: [
      'Can a copper-catalyzed Ullmann coupling replace Pd in aryl amine synthesis at <80°C?',
      'Does adding a Lewis acid co-catalyst improve the enantioselectivity of a Shi epoxidation?',
      'Can we scale a ball-milled mechanochemical amide coupling from 1 mmol to 1 mol?',
    ],
  },
  'Machine Learning': {
    caption: 'Runnable ML experiments — datasets, compute, evaluation, ablations.',
    examples: [
      'Does mixture-of-experts routing improve sample efficiency vs. a dense 7B model on math benchmarks?',
      'Can we distill a 70B instruction-tuned model into a 3B model while keeping 95% of MMLU performance?',
      'Does RLHF on synthetic preference data transfer to real-user preferences?',
    ],
  },
  Materials: {
    caption: 'Materials synthesis & characterization — XRD, SEM, mechanical tests.',
    examples: [
      'Does doping LiFePO₄ cathodes with 2% Nb improve cycle stability above 1000 cycles?',
      'Can we anneal perovskite films under IR flash instead of hotplate without losing grain size?',
      'Does adding graphene oxide nanosheets increase the tensile strength of PLA by >20%?',
    ],
  },
}

function domainInfo(d: Domain | undefined): { caption: string; examples: string[] } {
  if (!d) return { caption: '', examples: [] }
  const preset = DOMAIN_STARTERS[d.name]
  if (preset) return preset
  const firstSentence = (d.system_prompt ?? '').split(/[.!?]/)[0]?.trim() ?? ''
  return {
    caption: firstSentence || 'Custom research domain.',
    examples: [],
  }
}

function qualityHint(q: string): { level: 'ok' | 'warn' | 'info'; text: string } | null {
  const trimmed = q.trim()
  if (trimmed.length === 0) return null
  if (trimmed.length < 40)
    return {
      level: 'warn',
      text: 'A bit brief — add a mechanism, a measurable variable, or a comparison.',
    }
  const hasQuestion = /\?/.test(trimmed)
  const hasVerb =
    /\b(test|measure|investigate|compare|determine|evaluate|quantify|cause|effect|correlate|predict|improve|reduce|increase|enhance|inhibit|regulate)\b/i.test(
      trimmed,
    )
  if (!hasQuestion && !hasVerb)
    return {
      level: 'info',
      text: 'Tip: frame this as a testable question — "Does X cause / improve / reduce Y?"',
    }
  return { level: 'ok', text: 'Looks like a concrete, testable hypothesis.' }
}

const HYPOTHESIS_MAX = 4000

type Novelty = {
  score?: number | null
  rationale?: string | null
  references: Reference[]
}

type Plan = {
  protocol: { step: number; description: string; source_url?: string | null }[]
  materials: {
    name: string
    supplier?: string | null
    catalog_number?: string | null
    quantity?: string | null
    unit_cost_usd?: number | null
  }[]
  budget: { item: string; cost_usd: number }[]
  timeline: { phase: string; week_start: number; week_end: number; owner?: string | null }[]
  risks: { risk: string; mitigation: string }[]
  novelty: Novelty
}

type HistoryItem = {
  plan_id: string
  created_at: string
  hypothesis_text: string
  domain_name: string | null
  version: number
}

type FeedbackItem = {
  id: string
  plan_id: string
  field: string
  note: string | null
  created_at: string
  hypothesis_text: string | null
  domain_name: string | null
  original: unknown
  corrected: unknown
}

type AppSettings = {
  openai_model: string
  openai_base_url: string
  provider_host: string
  openai_api_key_set: boolean
  tavily_api_key_set: boolean
  db_path: string
}

type DomainFull = { id: string; name: string; system_prompt: string }

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

function noveltyLabel(score?: number | null): { text: string; cls: string } {
  if (score == null) return { text: 'Unknown', cls: 'badge' }
  if (score >= 0.7) return { text: 'Likely novel', cls: 'badge badge-high' }
  if (score >= 0.4) return { text: 'Similar work exists', cls: 'badge badge-med' }
  return { text: 'Close match found', cls: 'badge badge-low' }
}

type Route = '/' | '/new' | '/history' | '/admin' | `/plan/${string}`

function App() {
  const [route, setRoute] = useState<Route>('/new')

  const [domains, setDomains] = useState<Domain[]>([])
  const [domainId, setDomainId] = useState<string>('')

  const [question, setQuestion] = useState('')
  const [hypothesisId, setHypothesisId] = useState<string | null>(null)
  const [qc, setQc] = useState<Novelty | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [planId, setPlanId] = useState<string | null>(null)

  const [busy, setBusy] = useState<
    'qc' | 'plan' | 'feedback' | 'domains' | 'history' | 'admin' | null
  >(null)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const [history, setHistory] = useState<HistoryItem[]>([])
  const [feedbackLog, setFeedbackLog] = useState<FeedbackItem[]>([])
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null)
  const [fullDomains, setFullDomains] = useState<DomainFull[]>([])
  const [promptDraft, setPromptDraft] = useState<Record<string, string>>({})
  const [newDomainName, setNewDomainName] = useState('')
  const [newDomainPrompt, setNewDomainPrompt] = useState('')

  const [correctionField, setCorrectionField] = useState<string>('')
  const [correctionNote, setCorrectionNote] = useState<string>('')

  const totalBudget = useMemo(() => {
    if (!plan?.budget?.length) return null
    return plan.budget.reduce((acc, x) => acc + (Number.isFinite(x.cost_usd) ? x.cost_usd : 0), 0)
  }, [plan])

  const totalWeeks = useMemo(() => {
    if (!plan?.timeline?.length) return null
    return plan.timeline.reduce(
      (acc, t) => Math.max(acc, Number.isFinite(t.week_end) ? t.week_end : 0),
      0,
    )
  }, [plan])

  useEffect(() => {
    ;(async () => {
      setBusy('domains')
      try {
        const r = await fetch(`${API_BASE}/domains`)
        const data = await r.json()
        if (!r.ok) throw new Error(data?.detail ?? 'Failed to load domains')
        setDomains(data.domains ?? [])
        if (!domainId && data.domains?.[0]?.id) setDomainId(data.domains[0].id)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy(null)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function createHypothesisAndQc() {
    setError(null)
    setBusy('qc')
    setPlan(null)
    setQc(null)
    setHypothesisId(null)
    setPlanId(null)
    try {
      const h = await fetch(`${API_BASE}/hypotheses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: question, domain_id: domainId || null }),
      })
      const hData = await h.json()
      if (!h.ok) throw new Error(hData?.detail ?? 'Failed to create hypothesis')
      const hid = hData.hypothesis_id as string
      setHypothesisId(hid)

      const r = await fetch(`${API_BASE}/literature-qc`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hypothesis_id: hid }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data?.detail ?? 'Literature QC failed')
      setQc(data.novelty)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function generatePlan() {
    if (!hypothesisId) return
    setError(null)
    setBusy('plan')
    try {
      const r = await fetch(`${API_BASE}/generate-plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hypothesis_id: hypothesisId }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data?.detail ?? 'Plan generation failed')
      setPlan(data.plan)
      setPlanId(data.plan_id)
      setRoute(`/plan/${data.plan_id}`)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function submitFeedback(field: string, original: unknown, corrected: unknown, note?: string | null) {
    if (!planId) return
    setError(null)
    setBusy('feedback')
    try {
      const r = await fetch(`${API_BASE}/submit-feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_id: planId,
          scientist_id: null,
          field,
          original,
          corrected,
          note: note ?? null,
        }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data?.detail ?? 'Feedback submit failed')
      setToast('Correction saved. It will be used as a few-shot example for future plans in this domain.')
      window.setTimeout(() => setToast(null), 4000)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function loadHistory() {
    setError(null)
    setBusy('history')
    try {
      const r = await fetch(`${API_BASE}/history`)
      const data = await r.json()
      if (!r.ok) throw new Error(data?.detail ?? 'Failed to load history')
      setHistory(data.items ?? [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function openHistoryItem(planIdToLoad: string) {
    setError(null)
    setBusy('history')
    try {
      const r = await fetch(`${API_BASE}/plans/${planIdToLoad}`)
      const data = await r.json()
      if (!r.ok) throw new Error(data?.detail ?? 'Failed to load plan')
      const p = data.plan
      const hyp = data.hypothesis
      const litqc = data.literature_qc

      const loaded: Plan = {
        protocol: p.protocol ?? [],
        materials: p.materials ?? [],
        budget: p.budget ?? [],
        timeline: p.timeline ?? [],
        risks: p.risks ?? [],
        novelty: litqc
          ? {
              score: litqc.novelty_score,
              rationale: litqc.summary,
              references: litqc.references ?? [],
            }
          : { score: null, rationale: null, references: [] },
      }
      setPlan(loaded)
      setPlanId(planIdToLoad)
      setHypothesisId(hyp?.id ?? null)
      setQuestion(hyp?.text ?? '')
      setQc({
        score: litqc?.novelty_score ?? null,
        rationale: litqc?.summary ?? null,
        references: litqc?.references ?? [],
      })
      setRoute(`/plan/${planIdToLoad}`)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function loadAdmin() {
    setError(null)
    setBusy('admin')
    try {
      const [sRes, dRes, fRes] = await Promise.all([
        fetch(`${API_BASE}/settings`),
        fetch(`${API_BASE}/domains`),
        fetch(`${API_BASE}/feedback?limit=50`),
      ])
      const [sData, dData, fData] = await Promise.all([sRes.json(), dRes.json(), fRes.json()])
      if (!sRes.ok) throw new Error(sData?.detail ?? 'Failed to load settings')
      if (!dRes.ok) throw new Error(dData?.detail ?? 'Failed to load domains')
      if (!fRes.ok) throw new Error(fData?.detail ?? 'Failed to load feedback')
      setAppSettings(sData as AppSettings)
      const doms: DomainFull[] = dData.domains ?? []
      setFullDomains(doms)
      setPromptDraft(
        Object.fromEntries(doms.map((d) => [d.id, d.system_prompt])),
      )
      setFeedbackLog(fData.items ?? [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function saveDomainPrompt(id: string) {
    setError(null)
    setBusy('admin')
    try {
      const r = await fetch(`${API_BASE}/domains/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ system_prompt: promptDraft[id] ?? '' }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data?.detail ?? 'Failed to update domain')
      setToast('Domain prompt saved.')
      window.setTimeout(() => setToast(null), 3000)
      await loadAdmin()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function createNewDomain() {
    if (!newDomainName.trim() || newDomainPrompt.trim().length < 10) {
      setError('Name is required and system prompt must be at least 10 characters.')
      return
    }
    setError(null)
    setBusy('admin')
    try {
      const r = await fetch(`${API_BASE}/domains`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newDomainName.trim(),
          system_prompt: newDomainPrompt.trim(),
        }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data?.detail ?? 'Failed to create domain')
      setNewDomainName('')
      setNewDomainPrompt('')
      setToast('Domain created.')
      window.setTimeout(() => setToast(null), 3000)
      await loadAdmin()
      const rd = await fetch(`${API_BASE}/domains`)
      const ddata = await rd.json()
      setDomains(ddata.domains ?? [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  useEffect(() => {
    if (route === '/history') void loadHistory()
    else if (route === '/admin') void loadAdmin()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route])

  const correctionOptions = useMemo(() => {
    if (!plan) return [] as { key: string; label: string; value: unknown }[]
    const opts: { key: string; label: string; value: unknown }[] = []
    plan.protocol.forEach((s, i) =>
      opts.push({
        key: `protocol[${i}]`,
        label: `Protocol · step ${s.step}`,
        value: s,
      }),
    )
    plan.materials.forEach((m, i) =>
      opts.push({ key: `materials[${i}]`, label: `Material · ${m.name}`, value: m }),
    )
    plan.budget.forEach((b, i) =>
      opts.push({ key: `budget[${i}]`, label: `Budget · ${b.item}`, value: b }),
    )
    plan.timeline.forEach((t, i) =>
      opts.push({ key: `timeline[${i}]`, label: `Timeline · ${t.phase}`, value: t }),
    )
    plan.risks.forEach((r, i) =>
      opts.push({ key: `risks[${i}]`, label: `Risk · ${r.risk}`, value: r }),
    )
    return opts
  }, [plan])

  useEffect(() => {
    if (!correctionOptions.length) {
      setCorrectionField('')
      return
    }
    const current = correctionOptions.find((o) => o.key === correctionField)
    if (!current) {
      setCorrectionField(correctionOptions[0].key)
    }
  }, [correctionOptions, correctionField])

  async function submitCorrection() {
    if (!planId || !correctionField) return
    const opt = correctionOptions.find((o) => o.key === correctionField)
    if (!opt) return
    const note = correctionNote.trim()
    if (!note) {
      setError('Please describe what is wrong with this field before submitting.')
      return
    }
    await submitFeedback(correctionField, opt.value, note, note)
    setCorrectionNote('')
  }

  const noveltyBadge = noveltyLabel(qc?.score ?? null)

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <div className="brand-logo">CR</div>
          <div>
            <div className="brand-title">Crucible</div>
            <div className="brand-sub">Hypothesis → Literature QC → Experiment plan</div>
          </div>
        </div>
        <nav className="nav">
          <button
            className={route === '/new' || route === '/' ? 'is-active' : ''}
            onClick={() => setRoute('/new')}
            disabled={busy !== null}
          >
            New
          </button>
          <button
            className={route === '/history' ? 'is-active' : ''}
            onClick={() => setRoute('/history')}
            disabled={busy !== null}
          >
            History
          </button>
          <button
            className={route === '/admin' ? 'is-active' : ''}
            onClick={() => setRoute('/admin')}
            disabled={busy !== null}
          >
            Admin
          </button>
        </nav>
      </header>

      <p className="hero-lede">
        Crucible puts your hypothesis through a real test before you spend reagents.
        We run a web + academic literature sweep for a novelty signal, then generate a
        grounded, falsifiable plan: protocol, materials &amp; suppliers, budget,
        timeline, and risks.
      </p>

      {route === '/new' || route === '/' ? (
        <div className="stack">
          <section className="card">
            <div className="card-head">
              <h2>New hypothesis</h2>
              <span className="tag">
                <span className="tag-dot" /> Step 1
              </span>
            </div>

            {domains.length > 0 && (
              <div className="domain-picker">
                <div className="domain-picker-row">
                  <label className="muted" style={{ fontSize: 12 }}>Domain</label>
                  <select value={domainId} onChange={(e) => setDomainId(e.target.value)}>
                    {domains.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </div>
                {(() => {
                  const info = domainInfo(domains.find((d) => d.id === domainId))
                  return info.caption ? (
                    <div className="domain-caption">{info.caption}</div>
                  ) : null
                })()}
              </div>
            )}

            {(() => {
              const info = domainInfo(domains.find((d) => d.id === domainId))
              if (!info.examples.length) return null
              return (
                <div className="starters">
                  <div className="starters-label">Try one</div>
                  <div className="starters-chips">
                    {info.examples.map((ex, i) => (
                      <button
                        key={i}
                        type="button"
                        className="chip"
                        title={ex}
                        onClick={() => setQuestion(ex)}
                        disabled={busy !== null}
                      >
                        {ex.length > 80 ? ex.slice(0, 77) + '…' : ex}
                      </button>
                    ))}
                  </div>
                </div>
              )
            })()}

            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value.slice(0, HYPOTHESIS_MAX))}
              placeholder='e.g. "Can we improve perovskite solar cell efficiency by testing alternative annealing schedules?"'
              rows={4}
            />

            {(() => {
              const hint = qualityHint(question)
              const count = question.length
              const countClass =
                count === 0 ? 'muted' : count > HYPOTHESIS_MAX * 0.9 ? 'warn' : 'muted'
              return (
                <div className="hypo-meta">
                  {hint ? (
                    <span className={`hypo-hint hypo-hint-${hint.level}`}>{hint.text}</span>
                  ) : (
                    <span className="muted" style={{ fontSize: 12 }}>
                      Frame it as a question or a causal claim — the clearer the hypothesis,
                      the better the plan.
                    </span>
                  )}
                  <span className={`hypo-count ${countClass}`}>{count} / {HYPOTHESIS_MAX}</span>
                </div>
              )
            })()}

            <div className="row">
              <button
                className="btn-primary"
                onClick={createHypothesisAndQc}
                disabled={!question.trim() || busy !== null}
              >
                {busy === 'qc' ? 'Running literature QC…' : 'Run literature QC'}
              </button>
              <button onClick={generatePlan} disabled={!qc || busy !== null}>
                {busy === 'plan' ? 'Generating plan…' : 'Generate plan'}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => {
                  setQuestion('')
                  setHypothesisId(null)
                  setQc(null)
                  setPlan(null)
                  setPlanId(null)
                  setError(null)
                }}
                disabled={busy !== null || (!question && !hypothesisId && !qc && !plan)}
                title="Clear the question and start over"
              >
                Clear
              </button>
              <div className="muted" style={{ marginLeft: 'auto' }}>
                {hypothesisId ? (
                  <>
                    Hypothesis: <code>{hypothesisId.slice(0, 8)}…</code>
                  </>
                ) : (
                  '— no hypothesis yet'
                )}
              </div>
            </div>
            {error ? <div className="error">{error}</div> : null}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Literature novelty</h2>
              <span className="tag">
                <span className="tag-dot" /> Step 2
              </span>
            </div>

            {busy === 'qc' ? (
              <>
                <div className="skeleton wide" style={{ width: '60%' }} />
                <div className="skeleton" style={{ width: '90%' }} />
                <div className="skeleton" style={{ width: '80%' }} />
              </>
            ) : qc ? (
              <>
                <div className="novelty-row">
                  <div>
                    <div className="score">
                      {qc.score != null ? Math.round(qc.score * 100) : '—'}
                      {qc.score != null ? <span className="score-suffix">/ 100</span> : null}
                    </div>
                    <div className="score-label">Novelty score</div>
                  </div>
                  <span className={noveltyBadge.cls}>
                    <span className="badge-dot" />
                    {noveltyBadge.text}
                  </span>
                  <div className="muted" style={{ flex: 1, minWidth: 220 }}>
                    {qc.rationale}
                  </div>
                </div>

                {(() => {
                  const webRefs = qc.references.filter((r) => (r.source ?? '').toLowerCase() === 'tavily')
                  const paperRefs = qc.references.filter((r) => (r.source ?? '').toLowerCase() !== 'tavily')

                  const formatAuthors = (authors?: string[]) => {
                    if (!authors || authors.length === 0) return null
                    if (authors.length <= 3) return authors.join(', ')
                    return `${authors.slice(0, 3).join(', ')}, et al.`
                  }

                  const doiUrl = (doi?: string | null) =>
                    doi ? `https://doi.org/${doi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, '')}` : null

                  const renderWebRef = (r: Reference, idx: number) => (
                    <li key={idx} className="ref-card">
                      <div className="ref-head">
                        <div className="ref-title">
                          {r.url ? (
                            <a href={r.url} target="_blank" rel="noreferrer">
                              {r.title}
                            </a>
                          ) : (
                            r.title
                          )}
                        </div>
                        {r.source ? <span className="ref-source">{r.source}</span> : null}
                      </div>
                      <div className="ref-meta">
                        {[r.venue, r.year ? String(r.year) : null].filter(Boolean).join(' · ') || '—'}
                      </div>
                      {r.snippet ? <div className="ref-snippet">{r.snippet}</div> : null}
                    </li>
                  )

                  const renderPaperRef = (r: Reference, idx: number) => {
                    const authors = formatAuthors(r.authors)
                    const doiLink = doiUrl(r.doi)
                    return (
                      <li key={idx} className="ref-card">
                        <div className="ref-head">
                          <div className="ref-title">
                            {r.url ? (
                              <a href={r.url} target="_blank" rel="noreferrer">
                                {r.title}
                              </a>
                            ) : (
                              r.title
                            )}
                          </div>
                          {r.source ? <span className="ref-source">{r.source}</span> : null}
                        </div>
                        {authors ? <div className="ref-authors">{authors}</div> : null}
                        <div className="ref-meta">
                          {[r.venue, r.year ? String(r.year) : null]
                            .filter(Boolean)
                            .join(' · ') || '—'}
                          {doiLink ? (
                            <>
                              <span className="meta-sep">·</span>
                              <a
                                className="doi-link"
                                href={doiLink}
                                target="_blank"
                                rel="noreferrer"
                                title={r.doi ?? undefined}
                              >
                                DOI
                              </a>
                            </>
                          ) : null}
                        </div>
                        {r.snippet ? <div className="ref-snippet">{r.snippet}</div> : null}
                      </li>
                    )
                  }

                  if (qc.references.length === 0) {
                    return (
                      <ul className="refs">
                        <li className="muted">No sources found.</li>
                      </ul>
                    )
                  }
                  return (
                    <>
                      {webRefs.length > 0 ? (
                        <>
                          <h3 style={{ margin: '16px 0 2px', fontSize: 12, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                            Web sources
                          </h3>
                          <ul className="refs">{webRefs.map(renderWebRef)}</ul>
                        </>
                      ) : null}
                      {paperRefs.length > 0 ? (
                        <>
                          <h3 style={{ margin: '16px 0 2px', fontSize: 12, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                            Research papers
                          </h3>
                          <ul className="refs">{paperRefs.map(renderPaperRef)}</ul>
                        </>
                      ) : null}
                    </>
                  )
                })()}
              </>
            ) : (
              <div className="muted">Run literature QC to get a novelty signal and citations.</div>
            )}
          </section>
        </div>
      ) : null}

      {route.startsWith('/plan/') && plan ? (
        <section className="card" style={{ marginTop: 14 }}>
          <div className="card-head">
            <h2>Experiment plan</h2>
            <span className="tag">
              <span className="tag-dot" /> Step 3
            </span>
          </div>

          <div className="at-a-glance">
            <div className="metric">
              <div className="metric-label">Budget (USD)</div>
              <div className="metric-value">
                {totalBudget !== null ? `$${totalBudget.toLocaleString('en-US', { maximumFractionDigits: 0 })}` : '—'}
              </div>
            </div>
            <div className="metric">
              <div className="metric-label">Protocol steps</div>
              <div className="metric-value">{plan.protocol.length}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Materials</div>
              <div className="metric-value">{plan.materials.length}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Timeline</div>
              <div className="metric-value">
                {totalWeeks ? `${totalWeeks}w` : '—'}
              </div>
            </div>
            <div className="metric">
              <div className="metric-label">Risks tracked</div>
              <div className="metric-value">{plan.risks.length}</div>
            </div>
          </div>

          <details open>
            <summary>Protocol <span className="count-pill">{plan.protocol.length}</span></summary>
            <ol className="steps">
              {plan.protocol
                .slice()
                .sort((a, b) => a.step - b.step)
                .map((s) => (
                  <li key={s.step}>
                    <div className="step-main">{s.description}</div>
                    {s.source_url ? (
                      <div className="muted">
                        <a href={s.source_url} target="_blank" rel="noreferrer">
                          source
                        </a>
                      </div>
                    ) : null}
                  </li>
                ))}
            </ol>
          </details>

          <details>
            <summary>Materials &amp; supply chain <span className="count-pill">{plan.materials.length}</span></summary>
            <div className="table">
              <div className="thead">
                <div>Name</div>
                <div>Supplier</div>
                <div>Catalog</div>
                <div>Qty</div>
                <div>Unit $</div>
              </div>
              {plan.materials.map((m, idx) => (
                <div className="trow" key={idx}>
                  <div>{m.name}</div>
                  <div>{m.supplier ?? '—'}</div>
                  <div>{m.catalog_number ?? '—'}</div>
                  <div>{m.quantity ?? '—'}</div>
                  <div>{m.unit_cost_usd != null ? `$${m.unit_cost_usd}` : '—'}</div>
                </div>
              ))}
            </div>
          </details>

          <details>
            <summary>Budget <span className="count-pill">{plan.budget.length}</span></summary>
            <ul className="budget">
              {plan.budget.map((b, idx) => (
                <li key={idx}>
                  <strong>{b.item}</strong>
                  <span>${b.cost_usd.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          </details>

          <details>
            <summary>Timeline <span className="count-pill">{plan.timeline.length}</span></summary>
            <ol className="timeline">
              {plan.timeline.map((t, idx) => (
                <li key={idx}>
                  <div className="step-main">
                    {t.phase}{' '}
                    <span className="muted">
                      (weeks {t.week_start}–{t.week_end})
                    </span>
                  </div>
                  {t.owner ? <div className="muted">Owner: {t.owner}</div> : null}
                </li>
              ))}
            </ol>
          </details>

          <details>
            <summary>Risks &amp; mitigations <span className="count-pill">{plan.risks.length}</span></summary>
            <ul className="validation">
              {plan.risks.map((r, idx) => (
                <li key={idx}>
                  <strong>{r.risk}</strong>
                  <div className="muted" style={{ marginTop: 4 }}>
                    {r.mitigation}
                  </div>
                </li>
              ))}
            </ul>
          </details>

          <details>
            <summary>
              Inline correction · review loop{' '}
              <span className="count-pill">learning</span>
            </summary>
            <p className="muted" style={{ marginTop: 6 }}>
              Spot something wrong? Pick the field and describe what's off. Your note is
              saved to the feedback store and retrieved as a few-shot example the next time
              a plan is generated in this domain — so the model learns from your edits over
              time.
            </p>

            <div style={{ display: 'grid', gap: 10, marginTop: 10 }}>
              <div>
                <label className="muted" style={{ fontSize: 12 }}>
                  Field to correct
                </label>
                <select
                  value={correctionField}
                  onChange={(e) => setCorrectionField(e.target.value)}
                >
                  {correctionOptions.map((o) => (
                    <option key={o.key} value={o.key}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="muted" style={{ fontSize: 12 }}>
                  What's wrong with this field? (and what should it be instead)
                </label>
                <textarea
                  rows={4}
                  placeholder="e.g. Annealing time should be 2 hours, not 30 minutes — the DREB vector is heat-sensitive."
                  value={correctionNote}
                  onChange={(e) => setCorrectionNote(e.target.value)}
                />
              </div>

              <div className="row">
                <button
                  className="btn-primary"
                  onClick={submitCorrection}
                  disabled={busy !== null || !correctionField || !correctionNote.trim()}
                >
                  {busy === 'feedback' ? 'Submitting…' : 'Save correction'}
                </button>
                <button
                  className="btn-ghost"
                  onClick={() => setCorrectionNote('')}
                  disabled={busy !== null}
                >
                  Reset
                </button>
                <button className="btn-ghost" onClick={() => setRoute('/new')}>
                  Back to new hypothesis
                </button>
              </div>
            </div>
          </details>

          {error ? <div className="error">{error}</div> : null}
        </section>
      ) : null}

      {route === '/history' ? (
        <section className="card">
          <div className="card-head">
            <h2>History</h2>
            <span className="tag">
              <span className="tag-dot" /> {history.length} plans
            </span>
          </div>
          <p className="muted" style={{ marginTop: 0 }}>
            Every plan you generate is stored with its hypothesis, domain and version.
            Click a row to open it.
          </p>

          {busy === 'history' && history.length === 0 ? (
            <>
              <div className="skeleton wide" />
              <div className="skeleton wide" />
              <div className="skeleton wide" />
            </>
          ) : history.length === 0 ? (
            <div className="muted">
              No plans yet. Create a hypothesis, run literature QC, and generate a plan — it
              will show up here.
            </div>
          ) : (
            <div className="table history-table">
              <div className="thead">
                <div>When</div>
                <div>Hypothesis</div>
                <div>Domain</div>
                <div>Version</div>
                <div>Action</div>
              </div>
              {history.map((h) => (
                <div className="trow" key={h.plan_id}>
                  <div className="muted">
                    {new Date(h.created_at).toLocaleString()}
                  </div>
                  <div className="hist-hyp" title={h.hypothesis_text}>
                    {h.hypothesis_text}
                  </div>
                  <div>{h.domain_name ?? '—'}</div>
                  <div className="muted">v{h.version}</div>
                  <div>
                    <button
                      onClick={() => openHistoryItem(h.plan_id)}
                      disabled={busy !== null}
                    >
                      Open
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="row" style={{ marginTop: 10 }}>
            <button onClick={loadHistory} disabled={busy !== null}>
              {busy === 'history' ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
          {error ? <div className="error">{error}</div> : null}
        </section>
      ) : null}

      {route === '/admin' ? (
        <div className="stack">
          <section className="card">
            <div className="card-head">
              <h2>Runtime settings</h2>
              <span className="tag">Read-only</span>
            </div>
            <p className="muted" style={{ marginTop: 0 }}>
              These values come from the backend's environment ({'`backend/.env`'}). Change
              them there and restart the server.
            </p>
            {appSettings ? (
              <div className="table settings-table">
                <div className="trow">
                  <div className="muted">LLM model</div>
                  <div><code>{appSettings.openai_model}</code></div>
                </div>
                <div className="trow">
                  <div className="muted">Provider host</div>
                  <div><code>{appSettings.provider_host}</code></div>
                </div>
                <div className="trow">
                  <div className="muted">OpenAI-compatible base URL</div>
                  <div><code>{appSettings.openai_base_url}</code></div>
                </div>
                <div className="trow">
                  <div className="muted">OPENAI_API_KEY</div>
                  <div>
                    <span className={appSettings.openai_api_key_set ? 'badge badge-high' : 'badge badge-low'}>
                      <span className="badge-dot" />
                      {appSettings.openai_api_key_set ? 'set' : 'missing'}
                    </span>
                  </div>
                </div>
                <div className="trow">
                  <div className="muted">TAVILY_API_KEY</div>
                  <div>
                    <span className={appSettings.tavily_api_key_set ? 'badge badge-high' : 'badge badge-med'}>
                      <span className="badge-dot" />
                      {appSettings.tavily_api_key_set ? 'set' : 'optional, not set'}
                    </span>
                  </div>
                </div>
                <div className="trow">
                  <div className="muted">SQLite database</div>
                  <div><code>{appSettings.db_path}</code></div>
                </div>
              </div>
            ) : (
              <div className="skeleton wide" />
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Domain prompts</h2>
              <span className="tag">
                <span className="tag-dot" /> {fullDomains.length} domains
              </span>
            </div>
            <p className="muted" style={{ marginTop: 0 }}>
              The domain's system prompt is prepended to every plan generation for that
              domain. Edit it to steer tone, rigor, and required sections for a whole
              research area.
            </p>
            {fullDomains.map((d) => (
              <details key={d.id} style={{ marginTop: 10 }}>
                <summary>
                  {d.name}
                  <span className="count-pill">
                    {(promptDraft[d.id] ?? '').length} chars
                  </span>
                </summary>
                <textarea
                  rows={6}
                  value={promptDraft[d.id] ?? ''}
                  onChange={(e) =>
                    setPromptDraft((prev) => ({ ...prev, [d.id]: e.target.value }))
                  }
                  style={{ marginTop: 10 }}
                />
                <div className="row">
                  <button
                    className="btn-primary"
                    onClick={() => saveDomainPrompt(d.id)}
                    disabled={
                      busy !== null ||
                      (promptDraft[d.id] ?? '').trim() === (d.system_prompt ?? '').trim() ||
                      (promptDraft[d.id] ?? '').trim().length < 10
                    }
                  >
                    Save
                  </button>
                  <button
                    className="btn-ghost"
                    onClick={() =>
                      setPromptDraft((prev) => ({ ...prev, [d.id]: d.system_prompt }))
                    }
                    disabled={busy !== null}
                  >
                    Revert
                  </button>
                  <span className="muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
                    id: <code>{d.id.slice(0, 8)}…</code>
                  </span>
                </div>
              </details>
            ))}

            <details style={{ marginTop: 14 }}>
              <summary>+ Add a new domain</summary>
              <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
                <input
                  type="text"
                  placeholder="Name (e.g. Astrophysics)"
                  value={newDomainName}
                  onChange={(e) => setNewDomainName(e.target.value)}
                />
                <textarea
                  rows={5}
                  placeholder="System prompt — tell the LLM what persona to adopt for this domain."
                  value={newDomainPrompt}
                  onChange={(e) => setNewDomainPrompt(e.target.value)}
                />
                <div className="row">
                  <button
                    className="btn-primary"
                    onClick={createNewDomain}
                    disabled={busy !== null}
                  >
                    Create domain
                  </button>
                </div>
              </div>
            </details>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Feedback store</h2>
              <span className="tag">
                <span className="tag-dot" /> {feedbackLog.length} corrections
              </span>
            </div>
            <p className="muted" style={{ marginTop: 0 }}>
              Corrections you submit on generated plans. The most relevant ones (by
              hypothesis similarity within the same domain) are automatically included as
              few-shot examples on the next plan generation.
            </p>
            {feedbackLog.length === 0 ? (
              <div className="muted">No corrections submitted yet.</div>
            ) : (
              <ul className="validation">
                {feedbackLog.map((f) => (
                  <li key={f.id}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <strong>{f.field}</strong>
                      <span className="muted" style={{ fontSize: 12 }}>
                        {new Date(f.created_at).toLocaleString()}
                      </span>
                      {f.domain_name ? (
                        <span className="count-pill">{f.domain_name}</span>
                      ) : null}
                    </div>
                    {f.hypothesis_text ? (
                      <div className="muted" style={{ marginTop: 4, fontSize: 13 }}>
                        {f.hypothesis_text}
                      </div>
                    ) : null}
                    {f.note ? (
                      <div style={{ marginTop: 6 }}>
                        <em>“{f.note}”</em>
                      </div>
                    ) : null}
                    <details style={{ marginTop: 6 }}>
                      <summary>Show diff</summary>
                      <div className="diff">
                        <div>
                          <div className="muted" style={{ fontSize: 12 }}>before</div>
                          <pre className="diff-pre">
                            {JSON.stringify(f.original, null, 2)}
                          </pre>
                        </div>
                        <div>
                          <div className="muted" style={{ fontSize: 12 }}>after</div>
                          <pre className="diff-pre">
                            {JSON.stringify(f.corrected, null, 2)}
                          </pre>
                        </div>
                      </div>
                    </details>
                  </li>
                ))}
              </ul>
            )}
            <div className="row" style={{ marginTop: 10 }}>
              <button onClick={loadAdmin} disabled={busy !== null}>
                {busy === 'admin' ? 'Refreshing…' : 'Refresh'}
              </button>
            </div>
          </section>

          {error ? <div className="error">{error}</div> : null}
        </div>
      ) : null}

      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  )
}

export default App
