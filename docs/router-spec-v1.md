# Router Spec V1 — Lawyer Incorporated / Hermes

Version: 1.0
Owner: Hermes (CEO agent)
Approved by: Pending Aaron
Last updated: 2026-04-17

## 1) Purpose
Define deterministic model-routing rules for Hermes so model choice matches failure cost, legal/operational risk, and execution profile.

Primary goal: right model, right task, right escalation, every time.

## 2) Design Principles
1. Route by failure cost, not by model prestige.
2. Legal or external-risk tasks escalate up, never down.
3. High-volume internal workflows default to cheaper execution tiers.
4. External actions remain approval-gated unless explicitly authorized.
5. Routing must be observable, auditable, and easy to override.

## 3) Tier Definitions

Tier A: Frontier (high reasoning / high stakes)
- Default: openai GPT-5.4 (Codex subscription path)
- Fallback: Anthropic Claude Opus 4.6
- Use for: strategy, legal-risk framing, ambiguous high-impact decisions, architecture-level choices.

Tier B: Execution (tool-heavy, long chains, throughput)
- Default: configurable lower-cost execution model (provider-available)
- Fallback: Tier C model
- Use for: watchers, triage loops, structured extraction, bulk tool workflows, long multi-step tasks with low legal interpretation risk.

Tier C: Balanced (day-to-day quality/cost)
- Default: Anthropic Claude Sonnet 4.6
- Fallback: openai GPT-5.4 mini class equivalent when configured
- Use for: normal chat, drafting, coding tasks with moderate complexity, operational summaries.

Tier D: Local/Micro (always-on utility)
- Default: local/open small model (when deployed)
- Fallback: Tier B
- Use for: classification, routing labels, dedupe, simple summaries, heartbeat checks.

Note: Tier B and D concrete models are deployment-configurable. This spec defines policy, not vendor lock-in.

## 4) Task Classification Inputs
Every task is scored on these dimensions:
- Impact (Low/Med/High/Critical)
- Legal/ethical exposure (Low/High)
- Externality (Internal-only vs External-facing)
- Ambiguity (Low/Med/High)
- Tool-chain depth (0-2, 3-6, 7+ steps)
- Time horizon (single-shot vs recurring watcher)
- Data sensitivity (normal vs privileged/client-sensitive)

## 5) Routing Rules (Deterministic)

Rule 1: Mandatory high-tier escalation
Route to Tier A if ANY is true:
- Impact is High or Critical
- Legal/ethical exposure is High
- External-facing output could create obligations
- Ambiguity is High and wrong answer cost is meaningful

Rule 2: Balanced default
If Rule 1 is false and task is moderate complexity, route Tier C.

Rule 3: Execution lane
Route Tier B if ALL are true:
- Internal-only task
- Low legal exposure
- Tool-chain depth >= 3 OR recurring automation
- Objective is throughput/cost efficiency

Rule 4: Local/Micro lane
Route Tier D only when:
- Internal-only
- Reversible output
- Classification/summarization/routing task
- Fallback available to Tier B or C

Rule 5: Never auto-send externally from low tiers
Tier B/D may draft but must not send external communications unless standing authority exists.

## 6) Confidence + Escalation Gates

Confidence bands:
- High: >= 0.85
- Medium: 0.65 to 0.84
- Low: < 0.65

Escalate upward one tier when:
- Confidence < 0.85 on case-relevant conclusions
- Conflicting signals from two sources
- Missing critical context that changes outcome
- Detected legal-sensitive language in output

Hard-stop escalation to Aaron when:
- Proposed external action has legal obligation risk
- SOL/deadline ambiguity exists
- Financial decision threshold exceeded (policy-defined)
- Ethical/privacy uncertainty

## 7) External Action Guardrail Matrix

Allowed without approval:
- Internal summarization
- Internal tagging/classification
- Internal board/status updates
- Draft generation marked DRAFT only

Requires Aaron approval:
- Sending emails/SMS/calls externally
- Publishing posts/content externally
- Any client-facing legal-adjacent communication
- Any attorney-network supply-side outreach

## 8) Watcher + Follow-up Integration (Required)

All watcher/cron tasks must support open-loop tracking:
1. On schedule trigger, run task-specific check.
2. Update /Users/aaronwhaley/.hermes/active_followups.md:
   - [ ] open when unresolved
   - [~] waiting on external party
   - [x] completed with timestamp/outcome
3. Push result to Telegram origin chat (no manual dashboard check required).
4. If unresolved, include next-action draft and next-check schedule recommendation.

This is mandatory for case-critical follow-ups.

## 9) Output Contract (Per Routed Task)
Every routed execution should log:
- route_tier (A/B/C/D)
- chosen_model
- fallback_model
- confidence_score
- escalation_reason (if any)
- external_action_required (bool)
- approval_required (bool)

## 10) SLO Targets
- Routing correctness (human-reviewed sample): >= 90%
- False-negative escalation on high-risk tasks: < 2%
- Watcher alert-to-user delivery latency: <= 2 min from trigger
- Open-loop closure visibility: 100% of active critical follow-ups present in board

## 11) Implementation Plan (V1)

Phase 1: Policy codification
- Implement route evaluator helper (deterministic rules above).
- Add metadata block to outputs for route + confidence + escalation.

Phase 2: Guardrails
- Enforce approval gates for external actions by tier.
- Add automatic escalate-to-Aaron conditions.

Phase 3: Follow-up persistence
- Ensure cron jobs update active_followups.md by item ID.
- Enforce push delivery to origin chat.

Phase 4: Observability
- Add structured route logs.
- Weekly routing QA sample review.

## 12) Acceptance Tests
1. High-impact legal-sensitive prompt routes Tier A.
2. Internal recurring watcher routes Tier B and does not send external comms.
3. Low-risk classifier routes Tier D and falls back if unavailable.
4. Any low-confidence case conclusion escalates one tier.
5. Follow-up cron updates active board and pushes Telegram notification.
6. Unapproved external send attempt is blocked.

## 13) Immediate Defaults for Lawyer Inc
- Default interactive mode: Tier C (Claude Sonnet 4.6)
- Strategy/critical mode: Tier A (GPT-5.4 primary)
- Watchers/triage mode: Tier B
- Micro classifiers: Tier D when local model is online; else Tier B

## 14) Decision Lock
Strategic disagreement rule applies:
- Hermes gives concise pushback once on routing risk.
- Aaron decision is final and becomes locked policy until revised.
