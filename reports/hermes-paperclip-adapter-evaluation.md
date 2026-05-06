# Hermes Paperclip Adapter Evaluation

**Date:** 2026-04-29  
**Repo reviewed:** https://github.com/NousResearch/hermes-paperclip-adapter  
**Related platform:** https://github.com/paperclipai/paperclip  
**Scope:** Architecture/value report only. I did **not** install or start Paperclip.

## Bottom line

The `hermes-paperclip-adapter` is useful, but not because it gives Hermes new intelligence. It is useful because it lets Paperclip treat Hermes as a managed employee inside Paperclip's org-chart / task / heartbeat / budget system.

For our law-firm agent setup, the value is:

1. Paperclip can assign work to Hermes-backed agents.
2. Hermes can keep its existing tool system, skills, memory, MCP support, model routing, and local filesystem access.
3. Paperclip becomes the management dashboard: agents, roles, tasks, heartbeats, costs, run history, and governance.

I would treat it as a **control-plane adapter**, not as the primary agent runtime. Hermes remains the runtime. Paperclip becomes the board/dashboard that wakes Hermes agents and records what happened.

## What the adapter is

The adapter is a TypeScript package implementing Paperclip's adapter interface.

Paperclip custom adapters are expected to implement a `ServerAdapterModule` shape with at least:

- `type`
- `execute(ctx)`
- `testEnvironment(ctx)`
- optional session codec
- optional model list
- optional UI/CLI transcript parsing
- configuration docs

The Hermes adapter does that for Hermes Agent. It registers under:

```text
adapterType: hermes_local
```

The package exports:

```text
.
./server
./ui
./cli
```

Important files in the adapter:

```text
src/index.ts                shared adapter metadata/config docs
src/server/execute.ts       core execution: spawn Hermes CLI
src/server/test.ts          environment checks
src/server/detect-model.ts  model/provider detection from ~/.hermes/config.yaml
src/server/skills.ts        Hermes/Paperclip skill discovery
src/ui/parse-stdout.ts      Hermes stdout -> Paperclip transcript entries
src/ui/build-config.ts      UI config -> adapterConfig
src/cli/format-event.ts     terminal watch formatting
```

## How it works

### 1. Paperclip owns the run lifecycle

Paperclip creates an agent with:

```json
{
  "adapterType": "hermes_local",
  "adapterConfig": {
    "model": "anthropic/claude-sonnet-4",
    "timeoutSec": 300,
    "persistSession": true,
    "enabledToolsets": ["terminal", "file", "web"]
  }
}
```

Then Paperclip wakes the agent by task assignment, heartbeat, or issue comment.

### 2. The adapter builds a task prompt

`src/server/execute.ts` builds a prompt like:

```text
You are "{{agentName}}", an AI agent employee in a Paperclip-managed company.

Your Paperclip identity:
  Agent ID: {{agentId}}
  Company ID: {{companyId}}
  API Base: {{paperclipApiUrl}}

Assigned Task:
  Issue ID: {{taskId}}
  Title: {{taskTitle}}
  {{taskBody}}

Workflow:
  1. Work on the task using your tools
  2. Mark issue completed via Paperclip API
  3. Post a completion comment
```

It also has heartbeat/no-task behavior: list assigned issues, pick the highest priority open issue, or report nothing to do.

### 3. The adapter spawns Hermes CLI

The adapter runs Hermes as a child process:

```text
hermes chat -q "<rendered prompt>" -Q -m <model> --provider <provider> -t <toolsets> --source tool --yolo
```

Relevant flags:

- `chat -q` — single non-interactive query.
- `-Q` — quiet output.
- `-m` — model.
- `--provider` — OpenRouter/OpenAI/Anthropic/etc.
- `-t` — enabled toolsets.
- `--resume <session_id>` — resume prior Hermes session.
- `--source tool` — tags sessions as tool-originated so they do not clutter normal interactive history.
- `--yolo` — bypass dangerous-command approval prompts because Paperclip runs headless.

### 4. Hermes does the real work

Once launched, Hermes has its normal capabilities:

- terminal/file/web/browser tools,
- skills,
- memory,
- MCP,
- session search,
- model provider routing,
- local filesystem access,
- subagent delegation if available.

So the adapter does not reimplement Hermes. It gives Paperclip a way to supervise Hermes.

### 5. Results flow back into Paperclip

The adapter parses Hermes output for:

- final response / summary,
- session id,
- token usage if present,
- cost if present,
- error lines,
- structured transcript entries for the UI.

It returns an `AdapterExecutionResult` with fields like:

```text
exitCode
timedOut
provider
model
usage
costUsd
summary
resultJson
sessionParams
sessionDisplayId
```

If session persistence is enabled, Paperclip stores the Hermes session id and passes it back on the next heartbeat.

## What value it would add to our setup

### 1. Paperclip can manage Hermes-backed staff

For Lawyer Incorporated, this gives us a way to make Paperclip agents like:

```text
CEO / Hermes
COO
Marketing Director
Intake Specialist
Paralegal
Matchmaker
Follow-up Agent
```

where the actual execution runtime is still Hermes.

That means Paperclip provides the org-chart and task-control layer while Hermes provides the tools and reasoning.

### 2. Better dashboard than ad hoc cron/session tracking

Right now we have a mix of:

- Hermes cron jobs,
- Slack case rooms,
- Mission Control tasks,
- FirmVault files,
- Honcho memory,
- one-off scripts,
- local gateway sessions.

Paperclip could give a cleaner management UI for long-running agent work:

- what agents exist,
- what they are assigned to,
- what ran recently,
- what failed,
- what it cost,
- whether an agent is paused/idle/error,
- who reports to whom.

This is useful for operations work and business agents. It is less useful for high-volume email triage, which we already decided should not flood a task system.

### 3. Heartbeats with accountability

Paperclip's heartbeat model maps well to recurring work:

```text
Paralegal heartbeat
Follow-up heartbeat
Marketing content review
Attorney-network research
Billing/credit monitor
Case status sweep
```

Instead of a cron job silently running a prompt, Paperclip can show:

- the heartbeat run,
- logs,
- agent status,
- run result,
- issue/task status.

For law-firm operations, that audit trail matters.

### 4. Model/menu experimentation

This adapter allows per-agent model configuration. That lines up with your current desire to test model menu choices.

Example:

```text
Paralegal: anthropic/claude-sonnet-4.6 or openai/gpt-5.5
Coding: deepseek/deepseek-v4-pro, moonshotai/kimi-k2.6, gpt-5.5
Marketing: cheaper fast model
Research: high-context model
```

Paperclip gives a convenient place to see which agent is using which model.

### 5. Skills visibility

The adapter scans:

```text
~/.hermes/skills/
```

and exposes Hermes skills to Paperclip as read-only installed skills. That gives Paperclip visibility into what a Hermes-backed agent can do.

For us, that matters because the law-firm setup is increasingly skill-driven:

- FirmVault case context
- paralegal Slack routing
- Gmail case monitor
- medical chronologies
- Paperclip API management
- Mission Control API
- Google Workspace DWD

### 6. Useful for manager/worker patterns

A good use pattern would be:

```text
Paperclip CEO/COO agent creates/assigns task
      ↓
Paperclip wakes Hermes paralegal/coding/marketing agent
      ↓
Hermes executes in correct workspace/toolset
      ↓
Hermes posts result back to Paperclip
      ↓
Paperclip records run/cost/status
```

This is better than trying to make every Hermes cron job act like a project manager.

## Best use cases for us

### Strong fit

#### 1. Law-firm operations agents

Paperclip is good for staff-like roles:

```text
COO
Marketing Director
Follow-up Agent
Billing/ops monitor
Referral pipeline manager
```

These are business-operation functions where a dashboard, org chart, and task assignment make sense.

#### 2. Controlled recurring audits

Examples:

```text
weekly case completeness sweep
monthly referral-fee follow-up audit
daily billing/API-credit check
weekly website/SEO scan
case aging report
```

Paperclip's run history is useful here.

#### 3. Agent experiments

Paperclip is a good bench for comparing model behavior across agents:

```text
same role, different model
same task, different toolset
same heartbeat, different prompt
```

#### 4. Non-case company work

Use it for work that belongs to Lawyer Incorporated broadly:

```text
marketing plans
attorney network buildout
website changes
standard operating procedures
business dashboards
```

### Cautious fit

#### 1. Paralegal case work

This can work, but only if we preserve our case-isolation rules:

```text
case task -> correct FirmVault cwd -> correct AGENTS.md -> correct Honcho workspace case-<slug>
```

The adapter supports `cwd`, but Paperclip would need to set it correctly per case task/agent. If it wakes Hermes from a generic cwd, case context will be wrong.

For case work, Paperclip should either:

- create one agent per active case with `cwd` pinned to that FirmVault case folder, or
- include a reliable workspace/case resolver in adapterConfig/task metadata.

I would not let generic Paperclip paralegal tasks touch case data until this is deterministic.

#### 2. FirmVault batch workflows

Paperclip could coordinate FirmVault recipes, but Mission Control already fits recipe/task pipelines better. Paperclip is better as org/team supervisor; Mission Control is better as deterministic workflow runner.

So:

```text
Paperclip = staff/org/task dashboard
Mission Control = deterministic recipe execution
FirmVault = canonical case data
Hermes = execution/runtime brain/tools
Honcho = memory
```

### Poor fit

#### 1. High-volume email triage

We already learned this lesson. Do not send routine email triage into Paperclip tasks. That becomes noise.

Correct route remains:

```text
case email -> FirmVault + case Slack/Matrix + case Honcho
important ops email -> roscoe1/ops room + ops Honcho
junk -> ignore/archive
```

#### 2. Emergency/client communications

Paperclip can track the work, but final client-facing communication still needs Aaron review if it could create legal obligations.

#### 3. Anything requiring interactive terminal approval

The adapter uses `--yolo` because Paperclip agents are headless. That is operationally necessary, but it means sandboxing/working-directory containment matters more.

## Current repo quality / risk notes

### Good signs

- Small focused TypeScript package.
- MIT licensed.
- Direct implementation of Paperclip adapter architecture.
- Uses Paperclip adapter-utils instead of bespoke integration.
- Supports server, UI, and CLI surfaces.
- Has environment checks.
- Has provider/model detection.
- Has structured transcript parsing.
- Supports Hermes session resume.
- Supports Hermes skills visibility.

### Concerns

#### 1. Env var handling still looks risky

In `src/server/execute.ts`, env handling currently does:

```ts
const userEnv = config.env as Record<string, string> | undefined;
if (userEnv && typeof userEnv === "object") {
  Object.assign(env, userEnv);
}
```

But Paperclip often stores env secrets as structured objects, not plain strings, e.g. `{ type: "plain", value: "..." }` or similar. If so, this can pass an object instead of a string into the child process env.

That matches prior problems we saw: Hermes child process starts, but `OPENROUTER_API_KEY` is missing or invalid, causing OpenRouter 401 errors.

Before using this adapter in production, patch env resolution to accept:

```ts
"KEY": "value"
"KEY": { "value": "value" }
"KEY": { "type": "plain", "value": "value" }
```

And still set important API keys directly on the host/container env as belt-and-suspenders.

#### 2. README says `pip install hermes-agent`

Our prior experience says Hermes may need to be installed from GitHub rather than PyPI depending on packaging state. The Dockerfile/deploy docs should use the actually working install command for our environment.

#### 3. It assumes `hermes` CLI availability

The adapter only works if the Paperclip server environment has Hermes installed and configured.

That means in Render/Docker/self-hosting we must ensure:

- Python available,
- Hermes installed,
- `hermes` executable in PATH,
- `~/.hermes/config.yaml` or env present,
- model/provider keys available,
- skills mounted/copied if needed,
- workspace dirs exist.

#### 4. Case workspace isolation is not automatic by itself

The adapter supports `cwd`, but it does not know our FirmVault case-channel/case-Honcho conventions by default.

For law-firm use, we need a wrapper policy:

```text
Paperclip task has case_slug -> adapter cwd = FirmVault/cases/<slug> -> Hermes passive case Honcho workspace kicks in
```

Without that, Paperclip may wake a Hermes agent in the wrong directory.

#### 5. `--yolo` is both necessary and dangerous

Headless agents cannot approve terminal commands. So `--yolo` is pragmatic.

But it means we should scope agents by:

- cwd,
- toolsets,
- container/user permissions,
- allowed credentials,
- per-agent budget,
- one case folder when possible.

Do not give a case paralegal agent broad filesystem + broad credentials unless the workspace is isolated.

#### 6. Cost/runaway risk

Paperclip makes it easy to wake multiple agents. We already hit OpenRouter credit problems before. Paperclip budgets help, but concurrent wakeups can still burn money quickly.

Policy should be:

```text
stagger agent wakeups
budget cap each agent
no mass wake all agents
monitor OpenRouter/Honcho credits
```

## How this fits with our existing architecture

Recommended architecture:

```text
Aaron / Hermes CEO
        ↓
Paperclip dashboard for staff/org/task supervision
        ↓
Hermes-backed Paperclip agents via hermes_local adapter
        ↓
FirmVault / Slack or Matrix / Honcho / Gmail DWD / Mission Control as needed
```

Keep the system roles clear:

| System | Role |
|---|---|
| Hermes | primary runtime, tools, memory, skills, reasoning |
| Paperclip | agent org chart, dashboard, heartbeats, task governance, budgets |
| FirmVault | canonical case repository/data |
| Honcho | persistent memory, case workspaces |
| Slack/Matrix | real-time case/ops rooms |
| Mission Control | deterministic recipe/workflow execution |
| Cron | small recurring triggers where full dashboard overhead is unnecessary |

Paperclip should not replace Hermes, FirmVault, Honcho, or Mission Control. It should sit above them as the business-agent management layer.

## Specific value for Lawyer Incorporated

### Useful agent roster

If we pilot this, I would start with non-client-critical roles:

```text
1. COO / Ops Agent
   - SOPs, workflow cleanup, recurring system checks

2. Marketing Director
   - website/content/SEO tasks

3. Billing/Credits Monitor
   - OpenRouter, Honcho, Anthropic, RingCentral, subscriptions

4. Follow-up Agent
   - settlement/lien/referral-fee follow-up tracking, but drafts only

5. Research Agent
   - attorney network and vendor research
```

Then only later add:

```text
6. Paralegal Agent
   - case-specific only after cwd/Honcho/case-room scoping is proven
```

### Paperclip task examples

Good Paperclip tasks:

```text
AUDIT: Check OpenRouter/Honcho credits and summarize risk.
RESEARCH: Identify PI firms in Kentucky handling trucking cases.
OPS: Draft SOP for case email ingestion failure handling.
MARKETING: Review Lawyer Incorporated practice area pages for SEO gaps.
FOLLOW-UP: Build list of cases with no client update in 14 days.
```

Bad Paperclip tasks:

```text
Triage every Gmail email.
Send client settlement update without Aaron review.
Process every incoming case document without FirmVault guardrails.
Wake every agent every 5 minutes.
```

## What I would change before relying on it

### Must-fix

1. **Env resolution**
   - Normalize structured Paperclip env values to strings before passing to Hermes.
   - Ensure `OPENROUTER_API_KEY` reaches child process.

2. **Hermes install path**
   - Update docs/deploy to install Hermes the way our environment actually requires.

3. **Case cwd convention**
   - For case agents/tasks, ensure adapterConfig/task metadata sets:
     ```text
     cwd=/.../FirmVault/cases/<case_slug>
     ```
   - That will trigger our passive AGENTS.md + Honcho case workspace wiring.

4. **Per-agent toolset limits**
   - Do not give every Paperclip agent every Hermes tool.
   - Example:
     ```text
     Billing monitor: web, terminal maybe no file write
     Marketing: web, file, browser
     Paralegal: file, terminal, gmail/dwd skill, slack/matrix, no broad browser unless needed
     ```

5. **Concurrency limits**
   - No waking every agent at once.
   - Stagger scheduled heartbeats.

### Should-fix

1. Add model menu sync from our Hermes/OpenRouter choices.
2. Add Paperclip task template conventions for law-firm work.
3. Add adapter config presets:
   - `lawyerinc_ops`
   - `firmvault_case`
   - `marketing`
   - `coding`
4. Add run-result policy: case-sensitive outputs should summarize, not dump client records.
5. Add hooks to post important run results to Slack/Matrix rooms when needed.

## Pilot plan

I would not put this into production client/case work first.

### Phase 1 — dry dashboard pilot

Create 2–3 Hermes-backed Paperclip agents:

```text
Ops Monitor
Marketing Director
Research Agent
```

Give them narrow toolsets and harmless tasks.

Success criteria:

- wakes reliably,
- Hermes session resumes,
- results appear in Paperclip,
- costs appear or are at least traceable,
- OpenRouter key is passed correctly,
- no runaway loops.

### Phase 2 — controlled FirmVault pilot

Create one case-specific test agent:

```text
Paralegal - Michael Crader Test
cwd=/.../FirmVault/cases/michael-crader
```

Ask only read-only tasks first:

```text
Summarize current case state from AGENTS.md/state/wiki.
List missing medical records.
Find latest VA lien email imported into Honcho.
```

Success criteria:

- correct AGENTS.md loads,
- correct Honcho workspace is used,
- no cross-case memory leakage,
- no writes unless requested.

### Phase 3 — operations use

Move selected recurring business work into Paperclip:

```text
billing/credits monitor
website SEO checks
follow-up aging reports
attorney network research
```

Do **not** move routine email triage into Paperclip.

## Recommendation

Keep this adapter in the toolbox. It is directly relevant and likely valuable.

But use it for **management and supervised autonomous work**, not for core case-data routing.

The safe model is:

```text
Paperclip tells Hermes what job to do.
Hermes does the work using our existing skills/context/memory.
FirmVault remains the source of truth.
Honcho remains memory.
Slack/Matrix remains room-level operational chat.
Mission Control remains deterministic workflow execution.
```

If we wire it carefully, Paperclip can become the high-level dashboard for Lawyer Incorporated's AI staff. If we wire it casually, it will become another noisy task system. The adapter is useful; the governance design matters more than the package itself.

## Sources reviewed

- Hermes Paperclip Adapter GitHub: https://github.com/NousResearch/hermes-paperclip-adapter
- Adapter README and source files:
  - `README.md`
  - `src/server/execute.ts`
  - `src/server/test.ts`
  - `src/server/detect-model.ts`
  - `src/server/skills.ts`
  - `src/ui/parse-stdout.ts`
- Paperclip core repo: https://github.com/paperclipai/paperclip
- Paperclip custom adapter docs: https://www.mintlify.com/paperclipai/paperclip/agents/custom-adapters
- Paperclip adapter creation skill/doc: https://github.com/paperclipai/paperclip/blob/master/.agents/skills/create-agent-adapter/SKILL.md
