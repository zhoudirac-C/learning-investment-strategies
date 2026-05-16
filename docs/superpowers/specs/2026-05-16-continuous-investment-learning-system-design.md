# Continuous Investment Learning System Design

> Date: 2026-05-16  
> Repository: `learning-investment-strategies`  
> Branch: `docs/continuous-learning-system-spec`  
> Status: Draft for user review  
> Upstream stock analysis base: `zai-org/GLM-skills/skills/glmv-stock-analyst`, Apache-2.0, upstream main HEAD observed as `2ecd31c37e75671a4767342ba3a68a84c8f1b848` on 2026-05-16.  
> Local F10 source: `/Users/cong.zhou/Documents/quantitative/vnpy/docs/community/info/f10_financial_analysis_methodology.md`

## 1. Purpose

This repository builds a continuously updating investment-learning system for studying a specific blogger's investment framework, turning that framework into reusable agent skills, and applying the latest learned framework to stock analysis.

The project must preserve the strongest part of the existing `赛博青哥 Wiki` architecture: it can continuously ingest new blogger content, update the knowledge base, evolve the methodology, and keep a traceable operation log. The new repository is not a static skill package. It is a second-generation system that combines:

1. A living source and knowledge layer.
2. A claim-level evidence layer.
3. A compiled methodology and framework layer.
4. Agent skills that read the latest framework and evidence.
5. Evaluation cases that prevent method drift and regressions.

The guiding principle is:

```text
Daily blogger content -> LLM learning workflow -> claims/wiki/methodology updates -> framework updates -> skills use latest framework -> analysis/review outputs feed back into methodology review
```

## 2. Goals

### 2.1 Learn The Blogger's Investment Thinking

The system must support asking and answering questions such as:

- How does the blogger judge market cycle and sentiment stage?
- How does the blogger identify a main sector theme versus a short-lived topic?
- How does the blogger decide whether to hold, wait, reduce, or add exposure?
- What conditions make a stock's logic valid, weakened, or invalidated?
- Which historical cases demonstrate a specific rule?
- How has the blogger's view evolved over time?

Learning outputs must distinguish four layers:

1. Original source statement.
2. Extracted claim.
3. Methodology interpretation.
4. Agent inference.

The agent must never blur these layers.

### 2.2 Convert The Theory Into Skills

The system must produce skills that can be installed or copied into an agent skill directory. Skills should be workflow-oriented, not giant static documents. A skill must contain concise `SKILL.md` instructions and load deeper references only when needed.

The first release includes three core skills:

1. `qing-learning`: daily LLM-driven ingestion and learning update.
2. `qing-methodology-review`: periodic methodology maintenance and contradiction review.
3. `qing-stock-analysis`: stock analysis based on `glmv-stock-analyst`, enhanced with the blogger framework and F10 fundamentals.

`qing-trade-review` is intentionally out of v1 scope. It can be added after the learning and stock-analysis loop is stable.

### 2.3 Build A Stock Analysis Workflow

`qing-stock-analysis` must analyze a stock using three evidence streams:

1. Real market/company data from the GLM stock analyst data pipeline.
2. The blogger's latest framework, historical claims, and stock/sector traces.
3. F10 company fundamentals methodology: company type first, then statement quality, ROE/DuPont, cash flow, valuation method selection, and missing-field degradation.

The output should prioritize learning and framework application. It may include operational implications, but it must avoid becoming an unsupported buy/sell signal generator.

## 3. Non-Goals

The v1 system will not:

- Build a fully automated trading system.
- Place orders or connect to brokerage APIs.
- Guarantee investment performance.
- Convert every raw source into vector-only RAG and discard the wiki workflow.
- Hard-code the blogger's future opinions into scripts.
- Treat `sug` or direct trade recommendation as the primary product.
- Depend on one opaque LLM summary without source traceability.

## 4. Relationship To The Existing Wiki

The current `赛博青哥 Wiki` architecture is:

```text
Raw -> Wiki -> schema/log -> AI operations: ing/qry/trk/chk/sug
```

The new architecture keeps that spirit but adds two explicit compilation layers:

```text
sources/raw
  -> knowledge/claims
  -> knowledge/wiki
  -> methodology
  -> framework
  -> skills
  -> evals
```

The old project is a living content knowledge base. The new project is a living methodology and skill system. It must remain updateable like the old project, while making the investment thinking more executable and testable.

## 5. Repository Structure

The target repository structure is:

```text
learning-investment-strategies/
├── README.md
├── LICENSE
├── NOTICE
├── pyproject.toml
├── docs/
│   └── superpowers/
│       ├── specs/
│       └── plans/
├── sources/
│   ├── raw/
│   │   └── README.md
│   ├── incoming/
│   │   └── README.md
│   └── processed-log.md
├── knowledge/
│   ├── claims/
│   │   ├── README.md
│   │   └── index.md
│   ├── wiki/
│   │   ├── index.md
│   │   ├── log.md
│   │   ├── 投资方法论/
│   │   ├── 市场分析/
│   │   ├── 每日复盘/
│   │   └── 博主/
│   └── cases/
│       ├── README.md
│       ├── sector-cases/
│       └── stock-cases/
├── methodology/
│   ├── index.md
│   ├── market-cycle.md
│   ├── sector-rotation.md
│   ├── stock-selection.md
│   ├── f10-fundamental-analysis.md
│   ├── technical-analysis.md
│   ├── position-risk.md
│   └── decision-flow.md
├── framework/
│   ├── README.md
│   ├── learning-update-protocol.md
│   ├── stock-analysis-playbook.md
│   ├── methodology-review-protocol.md
│   ├── contradiction-policy.md
│   └── output-contracts.md
├── skills/
│   ├── qing-learning/
│   │   ├── SKILL.md
│   │   ├── references/
│   │   └── scripts/
│   ├── qing-methodology-review/
│   │   ├── SKILL.md
│   │   ├── references/
│   │   └── scripts/
│   └── qing-stock-analysis/
│       ├── SKILL.md
│       ├── references/
│       ├── scripts/
│       └── vendor/
│           └── glmv-stock-analyst/
├── third_party/
│   └── GLM-skills/
│       └── skills/
│           └── glmv-stock-analyst/
├── scripts/
│   ├── find_unprocessed.py
│   ├── lint_knowledge.py
│   ├── build_indexes.py
│   ├── extract_mentions.py
│   └── sync_glmv_stock_analyst.py
└── evals/
    ├── README.md
    ├── learning/
    ├── methodology-review/
    └── stock-analysis/
```

### 5.1 Why Both `third_party/` And Skill-Level `vendor/`

`third_party/GLM-skills/skills/glmv-stock-analyst/` stores a clean upstream snapshot for traceability. It should preserve upstream file layout and license notice.

`skills/qing-stock-analysis/vendor/glmv-stock-analyst/` stores the vendored runtime copy used by `qing-stock-analysis`. This copy can be patched for project-specific behavior. The patch history must explain what changed relative to upstream.

This dual layout prevents ambiguity:

- `third_party/` answers: what did we import?
- `skills/qing-stock-analysis/vendor/` answers: what does our skill execute?

## 6. Licensing And Attribution

The upstream `zai-org/GLM-skills` repository is Apache-2.0. When vendoring `glmv-stock-analyst`, the project must:

1. Preserve upstream `LICENSE` content in `third_party/GLM-skills/LICENSE`.
2. Add a root `NOTICE` entry describing the vendored component.
3. Record the upstream commit hash in `third_party/GLM-skills/VENDOR.md`.
4. Record local modifications in `skills/qing-stock-analysis/vendor/glmv-stock-analyst/PATCHES.md`.
5. Avoid claiming upstream GLM scripts as original work.

## 7. Data And Knowledge Layers

### 7.1 `sources/raw/`

This directory stores immutable blogger transcripts or manually prepared source notes. Raw files should not be edited after ingest except for clearly marked transcription corrections.

Filename convention:

```text
YYYY-MM-DD-类型-标题.md
```

Examples:

```text
2026-05-16-早盘-标题.md
2026-05-16-复盘-标题.md
2026-05-16-研报-标题.md
```

Each raw file should include source metadata when available:

```markdown
---
date: 2026-05-16
source_type: 早盘
source_author: 青枫浦上Q
source_url: ""
ingest_status: pending
---
```

### 7.2 `knowledge/claims/`

Claims are the evidence backbone. A claim is one atomic idea extracted from a source. It should be small enough to be cited and reviewed independently.

Claims can be stored as Markdown with YAML blocks or JSONL. v1 uses Markdown for human readability.

Required claim schema:

```yaml
id: claim-20260516-001
source_path: sources/raw/2026-05-16-早盘-标题.md
source_date: 2026-05-16
source_type: 早盘
extracted_at: 2026-05-16T00:00:00+08:00
claim_type: market-cycle | sector-theme | stock-view | methodology | risk | technical-signal | macro | operation
subject: "国产算力"
timeframe: intraday | short-term | trend | industry | permanent
statement: "..."
evidence_quote: "..."
interpretation: "..."
confidence: high | medium | low
status: active | superseded | contradicted | expired | case-only
supersedes: []
contradicts: []
links:
  wiki_pages: []
  methodology_pages: []
  cases: []
```

Rules:

- `statement` should summarize what the blogger said or implied.
- `evidence_quote` should quote only a short source fragment.
- `interpretation` is the agent's reading and must not be confused with source text.
- `status` must change when later content invalidates or supersedes a claim.
- If no clear evidence exists, do not create a claim.

### 7.3 `knowledge/wiki/`

The wiki remains the narrative knowledge layer. It is optimized for reading and cross-linking, not for atomic traceability. Wiki pages are compiled from raw sources and claims.

Required wiki sections:

```text
投资方法论
市场分析
每日复盘
博主
数据
```

The wiki must keep:

- `knowledge/wiki/index.md`: human-readable navigation and current page inventory.
- `knowledge/wiki/log.md`: append-only operation log.

### 7.4 `knowledge/cases/`

Cases store historical examples used to test and teach the framework. A case should contain:

- Background market state.
- Blogger's original view.
- Key claims.
- What happened afterward.
- What method rule the case supports or challenges.
- Whether the case remains active, historical, or invalidated.

Case types:

```text
sector-cases: sector/theme evolution cases
stock-cases: individual stock cases
methodology-cases: rules illustrated by history
```

### 7.5 `methodology/`

`methodology/` stores the learned theory in long-form pages. These pages answer “what is the blogger's framework?” rather than “what happened on a day?”

Core pages:

- `market-cycle.md`: market state, sentiment stages, timing windows.
- `sector-rotation.md`: main theme, sub-theme, high-low switch, crowdedness.
- `stock-selection.md`: core stock, follow-up stock,补涨, case-only stock.
- `f10-fundamental-analysis.md`: F10 company fundamentals methodology.
- `technical-analysis.md`: Bollinger, moving average, volume-price, top/bottom structure.
- `position-risk.md`: sizing, add/reduce rules, invalidation, no-trade conditions.
- `decision-flow.md`: complete analysis sequence.

### 7.6 `framework/`

`framework/` stores executable playbooks used by skills. It is more concise and operational than `methodology/`.

Examples:

- `learning-update-protocol.md`: how LLM ingests new content.
- `stock-analysis-playbook.md`: how to analyze a stock.
- `methodology-review-protocol.md`: how to periodically revise methods.
- `contradiction-policy.md`: how to resolve evolving or conflicting views.
- `output-contracts.md`: exact output sections for each skill.

A skill should usually read `framework/` first and only load detailed `methodology/` or `knowledge/` files when needed.

## 8. Skill Architecture

### 8.1 Shared Skill Design Principles

All project skills must follow these rules:

1. `SKILL.md` contains workflow and routing instructions, not the full knowledge base.
2. Detailed domain knowledge lives in `references/` and repository-level `framework/` or `methodology/`.
3. Scripts provide deterministic assistance only: finding files, linting, indexing, fetching data, and checking structure.
4. LLM performs semantic work: reading, extracting, reconciling, interpreting, and updating methods.
5. Every material claim must cite source path and date.
6. Skills must output uncertainty and missing evidence explicitly.
7. Skills must not invent market data, company data, or blogger opinions.

### 8.2 `qing-learning`

Purpose: daily or incremental learning from new blogger content.

Trigger examples:

```text
ing
学习今天内容
消化这篇早盘
更新博主方法论
把 Raw 里的新稿入库
```

Workflow:

```text
1. Run helper script to find unprocessed raw files.
2. Read one source file fully from beginning to end.
3. Extract atomic claims with evidence.
4. Classify claims by topic, timeframe, and method category.
5. Compare claims against existing active claims and methodology pages.
6. Decide whether to update wiki only, methodology, framework, or cases.
7. Update claims, wiki, methodology/framework if justified.
8. Update index and operation log.
9. Produce a learning report with changes and review flags.
```

LLM-owned responsibilities:

- Full-text reading.
- Claim extraction.
- Methodology classification.
- Contradiction detection.
- Deciding whether a new idea is short-term context or durable method.
- Updating narrative pages and playbooks.

Script-owned responsibilities:

- Listing pending raw files.
- Checking whether a raw file appears in processed log.
- Building indexes.
- Detecting broken links and missing metadata.
- Counting stock/sector mentions.

Required output:

```markdown
# Learning Update Report

## Sources Processed
## New Claims
## Methodology Updates
## Framework Updates
## Stock/Sector Tracking Updates
## Contradictions Or Superseded Views
## Human Review Needed
## Files Changed
```

### 8.3 `qing-methodology-review`

Purpose: periodically maintain and clean the evolving framework.

Trigger examples:

```text
复盘最近一周方法论变化
检查博主框架有没有变
review methodology
查矛盾和过期观点
```

Workflow:

```text
1. Select review window: default last 7 calendar days, configurable.
2. Load claims and wiki log for the review window.
3. Group changes by market-cycle, sector, stock-selection, F10/fundamental, technical, position/risk.
4. Compare against current methodology and framework pages.
5. Mark changes as: no change, clarification, extension, correction, contradiction, expiration.
6. Update methodology/framework pages when rules are durable enough.
7. Mark claims as superseded/contradicted/expired where appropriate.
8. Produce methodology review report and update logs.
```

Durability rule:

A new idea may update `framework/` when one of these is true:

- The blogger explicitly states it as a rule or framework.
- The idea appears repeatedly across multiple sources.
- The idea explains a prior contradiction and improves the decision flow.
- The idea changes an existing operational rule such as add/reduce, wait/act, or invalidation.

A new idea should remain only in wiki/cases when it is:

- One-day market context.
- A single stock comment without method implication.
- A temporary macro event with no repeated framework value.
- Ambiguous and unsupported by evidence.

Required output:

```markdown
# Methodology Review Report

## Review Window
## Durable Method Changes
## Clarifications
## Contradictions
## Expired Or Downgraded Claims
## Framework Files Updated
## Remaining Questions
```

### 8.4 `qing-stock-analysis`

Purpose: analyze a stock using the GLM stock analyst data pipeline, blogger framework, and F10 fundamentals.

This skill is based on `zai-org/GLM-skills/skills/glmv-stock-analyst`. It must vendor/copy that skill into the repository and optimize it rather than rewriting from scratch.

Preserved upstream GLM capabilities:

- Confirm stock code through search.
- Support A-share, Hong Kong, and US stocks.
- Fetch market data, basic fundamentals, K-line charts, intraday charts, fund flow, and research/report data.
- Require the model to inspect generated chart images.
- Search precise news manually rather than relying on noisy fallback news.
- Produce `report.md`, `report.html`, and optional PDF.

Project-specific enhancements:

1. Load latest `framework/stock-analysis-playbook.md`.
2. Search `knowledge/claims`, `knowledge/wiki`, and `knowledge/cases` for the stock, sector, and related concepts.
3. Apply F10 fundamentals methodology from `methodology/f10-fundamental-analysis.md`.
4. Add blogger-framework sections to the report.
5. Separate evidence from interpretation.
6. Add invalidation conditions and fields to watch next.
7. Explicitly degrade analysis when data is missing.

Workflow:

```text
1. Confirm stock identity and code.
2. Run vendored GLM data fetch script.
3. Read `summary.json`, `data.json`, and generated charts.
4. Inspect daily and intraday K-line images directly.
5. Search precise stock news and recent company events.
6. Query local knowledge for blogger mentions and sector traces.
7. Apply blogger stock-analysis playbook.
8. Apply F10 fundamental workflow.
9. Generate `report.md` with GLM evidence sections plus Qing-framework sections.
10. Convert to HTML and optionally PDF.
11. Reply with concise webchat summary and link/path to report.
```

Required report sections:

```markdown
# Stock Analysis Report

## 1. Identity And Data Coverage
## 2. Blogger Framework Positioning
## 3. Market And Sector Context
## 4. Technical And Funds Analysis
## 5. F10 Fundamental Analysis
## 6. Historical Blogger Mentions And View Evolution
## 7. Bull/Bear Evidence Table
## 8. Invalidation Conditions
## 9. Watchlist Fields For Next Update
## 10. Learning Conclusion
## 11. Risk Notice
```

The skill may include operational implications, but must phrase them as framework interpretation:

```text
Good: Under the blogger's current framework, this stock is closer to a sector-core trend candidate, but the current technical position is not a clean low-risk entry.
Bad: Buy now.
```

## 9. F10 Fundamental Analysis Integration

The F10 methodology source must be copied or summarized into:

```text
methodology/f10-fundamental-analysis.md
skills/qing-stock-analysis/references/f10-financial-analysis.md
```

The canonical F10 principle is:

```text
Do not start with a raw indicator. First identify company type and business model, then choose the appropriate valuation and quality checks.
```

The required F10 sequence is:

```text
1. Company type identification.
2. Three-statement quality check.
3. Profitability: gross margin, net margin, ROE.
4. DuPont decomposition: net margin, asset turnover, equity multiplier.
5. Growth quality: revenue, profit, and operating cash flow consistency.
6. Balance sheet risk: cash, receivables, inventory, debt.
7. Valuation method selection: PE / PB / PEG / PS.
8. Valuation tolerance adjustment by industry, interest-rate environment, market volume, and risk appetite.
9. Conclusion: undervalued / reasonable / overvalued / not estimable.
10. Risk points and next-report tracking fields.
```

Company type mapping:

```text
Stable profit leader -> ROE, PE, cash-flow quality
Asset-driven company -> PB, ROE, asset quality
Strong cyclical company -> PB and cycle position; PE can be misleading
High-growth company -> PEG, PE, R&D/order validation
Loss-making or profit-suppressed company -> PS, gross margin, revenue growth, path to profitability
Speculative stock -> fundamentals only as bottom-line risk check
```

Missing data rule:

If PE/PB/PS/PEG, market cap, forecast growth, industry peer valuation, cash flow, or statements are missing, the report must say which part is degraded and avoid pretending to have a complete valuation system.

## 10. Continuous Update Rules

### 10.1 Daily Ingest Rule

For each new raw source:

1. Process the source individually unless the user explicitly asks for batch mode.
2. Read the entire source before writing updates.
3. Extract claims before updating wiki/methodology.
4. Update short-term daily pages even when no durable methodology changes are found.
5. Update methodology/framework only when the durability rule is met.
6. Update log after all writes.
7. Include a human-review list for ambiguous changes.

### 10.2 Contradiction Policy

When a new claim conflicts with an older claim:

1. Do not delete the old claim.
2. Link both claims using `contradicts` or `supersedes`.
3. Identify whether the difference is time horizon, market state, stock-specific context, or true contradiction.
4. Update wiki and methodology with the reason if clear.
5. If unclear, mark human review required.

Possible contradiction categories:

```text
timeframe-shift: short-term bearish, long-term bullish
cycle-shift: view changed because market stage changed
logic-broken: old stock/sector logic invalidated
risk-repriced: macro or liquidity risk changed tolerance
true-conflict: no clear explanation; requires review
```

### 10.3 Methodology Evolution Rule

A methodology update must record:

- What changed.
- Which source or claims triggered it.
- Whether it is a new rule, clarification, exception, or deprecation.
- Which framework page changed.
- How stock analysis should behave differently after the change.

### 10.4 Skill Update Rule

Skills should not require editing `SKILL.md` for every new blogger view. Daily changes should update claims, wiki, methodology, or framework. `SKILL.md` changes are reserved for workflow changes, new tools, new output contracts, or recurring failure modes.

## 11. Script Responsibilities

Scripts are assistants, not the learning brain.

Allowed script responsibilities:

- `find_unprocessed.py`: list raw files not recorded in `sources/processed-log.md`.
- `build_indexes.py`: rebuild `knowledge/wiki/index.md`, `knowledge/claims/index.md`, and case indexes.
- `lint_knowledge.py`: check metadata, broken links, missing claim fields, duplicate IDs, stale logs.
- `extract_mentions.py`: extract stock names, stock codes, sectors, and dates for candidate review.
- `sync_glmv_stock_analyst.py`: copy upstream GLM stock analyst files into `third_party/` and the vendored skill path.

Forbidden script responsibilities:

- Deciding whether a new investing idea is durable methodology.
- Rewriting the framework without LLM review.
- Generating final stock conclusions without evidence and model reasoning.
- Hard-coding future blogger opinions.

## 12. Evaluation Strategy

The project needs regression evaluations because methodology can drift.

### 12.1 Learning Evals

Input: a historical raw source.  
Expected behavior:

- Extract key claims.
- Update daily wiki page.
- Identify whether methodology changed.
- Avoid over-promoting one-day context into durable framework.

### 12.2 Methodology Review Evals

Input: a review window with known contradictions or changes.  
Expected behavior:

- Identify superseded claims.
- Explain whether a conflict is timeframe, cycle, logic-broken, risk-repriced, or true conflict.
- Update methodology only when durable.

### 12.3 Stock Analysis Evals

Input: stock name/code and known historical context.  
Expected behavior:

- Use GLM-style data and chart workflow.
- Use local blogger claims and cases.
- Apply F10 method based on company type.
- Output missing-data degradation when fields are unavailable.
- Avoid unsupported buy/sell commands.

### 12.4 Acceptance Criteria

A v1 release is acceptable when:

1. A new raw file can be ingested into claims, wiki, methodology, and logs.
2. A methodology review can detect at least one durable change and one non-durable context item.
3. A stock analysis report can be generated using vendored GLM scripts plus F10 and blogger framework sections.
4. All generated reports cite source paths or data files for important claims.
5. `lint_knowledge.py` passes on the repository.
6. Vendored GLM source, license, and modifications are documented.

## 13. Implementation Phases

### Phase 1: Repository Foundation

Create the repository structure, root documentation, license/notice files, and Superpowers docs.

Deliverables:

- `README.md`
- `LICENSE`
- `NOTICE`
- `docs/superpowers/specs/...`
- `docs/superpowers/plans/...`
- Initial `.gitkeep` files for directories that must exist before implementation content is added.

### Phase 2: Knowledge Schema And Helper Scripts

Create raw, claims, wiki, methodology, and framework directories with schemas and linting scripts.

Deliverables:

- Claim schema documentation.
- Processed log format.
- Index builder.
- Knowledge linter.
- Mention extractor.

### Phase 3: `qing-learning`

Create the first skill for daily ingest and learning updates.

Deliverables:

- `skills/qing-learning/SKILL.md`
- `skills/qing-learning/references/ingest-protocol.md`
- `skills/qing-learning/references/claim-schema.md`
- `skills/qing-learning/scripts/find_unprocessed.py` wrapper or link to root script.
- Evals for historical raw files.

### Phase 4: F10 Methodology Integration

Copy and normalize the F10 methodology into project references.

Deliverables:

- `methodology/f10-fundamental-analysis.md`
- `skills/qing-stock-analysis/references/f10-financial-analysis.md`
- Stock-analysis report contract updated with F10 sections.

### Phase 5: Vendor GLM Stock Analyst

Vendor `zai-org/GLM-skills/skills/glmv-stock-analyst`.

Deliverables:

- Clean upstream snapshot under `third_party/GLM-skills/skills/glmv-stock-analyst/`.
- Runtime vendor copy under `skills/qing-stock-analysis/vendor/glmv-stock-analyst/`.
- `VENDOR.md` with upstream URL, commit, date, and license.
- `PATCHES.md` for local modifications.

### Phase 6: `qing-stock-analysis`

Build the enhanced stock-analysis skill on top of the vendored GLM workflow.

Deliverables:

- `skills/qing-stock-analysis/SKILL.md`
- References for GLM workflow, F10 workflow, blogger framework workflow, report contract.
- Script wrappers that call vendored GLM scripts.
- Example reports for at least two stocks.

### Phase 7: `qing-methodology-review`

Build the periodic review skill.

Deliverables:

- `skills/qing-methodology-review/SKILL.md`
- Contradiction policy reference.
- Review output contract.
- Evals for methodology drift and contradiction handling.

### Phase 8: End-To-End Regression

Run a complete workflow:

```text
raw source -> learning update -> methodology review -> stock analysis -> eval/lint pass
```

Deliverables:

- Example raw source fixture.
- Example claim output.
- Example stock report.
- Passing lint script.
- Final implementation notes.

## 14. Open Decisions

The following decisions are intentionally fixed for v1 to avoid implementation ambiguity:

1. `qing-stock-analysis` vendors/copies `glmv-stock-analyst`; it does not call only the installed local skill.
2. Raw ingest remains LLM-driven; scripts only support deterministic file/data operations.
3. F10 methodology is a first-class part of stock analysis, not an optional appendix.
4. Full historical Raw migration is not required for v1. The project can start with selected fixtures and later import more content.
5. The system optimizes for learning and analysis, not automated trade execution.
6. Daily methodology changes update `framework/`; `SKILL.md` changes are reserved for workflow changes.

## 15. Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| LLM over-promotes one-day views into durable methodology | Framework becomes noisy | Durability rule + methodology review evals |
| Stock analysis becomes unsupported buy/sell advice | Misuse risk | Output contracts require framework interpretation, risk notice, invalidation conditions |
| Vendored GLM code drifts from upstream | Maintenance burden | `VENDOR.md`, `PATCHES.md`, sync script, upstream commit tracking |
| Claims become too verbose | Hard to review | Atomic claim schema and index |
| Raw/wiki/framework diverge | Skills use stale logic | Learning workflow updates all affected layers and logs changed files |
| F10 fields missing | False precision | Required degraded-analysis section |
| Too much content in SKILL.md | Context bloat | Progressive disclosure through references |

## 16. Review Checklist

Before implementation starts, confirm:

- The repository is intended to be a continuous learning system, not a static skill bundle.
- `qing-stock-analysis` will vendor/copy GLM stock analyst and modify it locally.
- The F10 methodology file will be copied into project methodology and skill references.
- The first implementation plan should prioritize repository foundation, schemas, `qing-learning`, and GLM vendoring before advanced evals.
- The user accepts that scripts support but do not replace LLM semantic learning.

