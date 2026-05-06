# Legacy Law Firm Tools Audit

Source reviewed: `/Volumes/X10 Pro/projects/Tools`  
Audit date: 2026-04-28  
Inventory JSON: `reports/legacy_law_tools_inventory.json`

## Executive Summary

There is real value here. This is not junk. The folder contains **99 tool directories with `tool.yaml`**, **199 Python files**, and a prior validation report showing most were structurally working in the old Roscoe/OpenClaw setup. The main problem is not tool quality; it is **runtime drift**:

- old paths like `/Volumes/X10 Pro/projects` and `/Users/aaronwhaley/RoscoeDesktop/...`,
- old JSON/FalkorDB assumptions instead of current FirmVault case folders, `state.yaml`, wiki-agent pages, and Honcho workspaces,
- old Slack/Gmail/Calendar pathways now superseded by Hermes tools and Google Workspace DWD,
- some credential/web automation tools needing secret-path cleanup and explicit human approval gates.

Bottom line: **keep the PI/paralegal domain tools and port the useful logic into Hermes-native skills/tools. Do not wholesale import the old tool framework.**

## Best Candidates to Keep and Port First

These are the ones most likely to save us from reinventing work.

| Priority | Tool | Why keep it | Porting target |
|---|---|---|---|
| P0 | `generate_demand_pdf` | 1,019 lines of demand package/PDF/exhibit compilation logic. This is directly useful. | Hermes/FirmVault demand package skill/tool; adapt to current demand-letter workflow and FirmVault exhibits. |
| P0 | `medical_request_generator` | 616 lines for provider letters + HIPAA merge. Matches current medical-provider setup workflow. | FirmVault medical-record request generation; use current templates and DocuSign/HIPAA paths. |
| P0 | `settlement_calculator` | 643 lines of settlement distribution math, fees, liens, bills, net client. | Settlement statement generator; keep human review gate. |
| P0 | `pip_waterfall` | Kentucky PIP waterfall decision logic. Domain-specific and valuable. | Intake/insurance analysis skill; cite as operational aid, not legal advice to clients. |
| P0 | `negotiation_tracker` | 603 lines tracking offers/counteroffers/history. Matches negotiation phase tasks. | FirmVault `negotiation/` state + Slack/Honcho summaries. |
| P0 | `checkin_tracker` | 640 lines for bi-weekly treatment check-ins. Directly useful for client follow-up. | Paralegal heartbeat / Follow-up Agent workflow. |
| P0 | `kyecourts_docket` | Kentucky eCourts Playwright docket retrieval. Already aligned with litigation/case updates. | Modernize Playwright, secrets, output to FirmVault litigation folder. |
| P0 | `kyecourts_download_documents` | Downloads CourtNet/eCourts docs. Directly useful. | FirmVault legal docs import pipeline, with explicit auth/approval policy. |
| P0 | `case_file_organizer` | 652 lines of Gemini document classification + manifest/apply workflow. Not apply-ready as-is, but logic is valuable. | Fold into current FirmVault answer-key / frontmatter / organization pipeline; preserve as reference. |
| P0 | `read_pdf` | Tiered PDF extraction with caching. Useful for attachments and docs. | Use as fallback extractor behind current OCR/document skill. |
| P0 | `chronology_tools` | Medical chronology generation + research cache + PDF output. | Merge into Valtrus-style chronology workflow. |
| P1 | `outstanding_medical_records_report` | Report pending/missing records. | Paralegal dashboard / weekly case status. |
| P1 | `outstanding_medical_bills_report` | Report unpaid medical bills. | Damages/lien workflow. |
| P1 | `active_negotiations_report` | Negotiation status report. | Follow-up Agent / litigation dashboard. |
| P1 | `create_file_inventory` | Case folder inventory reports. | FirmVault audit/repair preflight. |
| P1 | `import_documents` | Batch PDF import and indexing. | FirmVault intake/import staging flow. |
| P1 | `combine_letter_and_hipaa` | Combines request letters + HIPAA PDFs. | Medical request package builder. |
| P1 | `combine_pdfs` | PDF combination / markdown-to-PDF utility. | Keep as utility, but may be replaced by existing PDF tools. |
| P1 | `split_large_pdf` | PDF chunking for large document analysis. | Attachment/document processing pipeline. |
| P1 | `read_multimodal_file`, `analyze_audio`, `analyze_image`, `analyze_video`, `view_pdf` | Useful multimodal wrappers, especially audio/voicemail. | Rework to Hermes vision/TTS/OCR tools; do not keep old model-specific assumptions. |
| P1 | CourtListener tools: `search_case_law`, `get_docket_details`, `get_opinion_full_text`, `find_my_cases`, `explore_citations`, `oral_arguments_search`, `monitor_upcoming_dates` | Useful research/docket utilities with API logic already written. | Legal research skill/toolset; keep citations verified, never hallucinate. |
| P1 | Medical research: `pubmed_search`, `semantic_scholar_search`, `expert_witness_lookup` | Useful for causation/background research. | Research mode; keep separate from client-facing legal/medical conclusions. |

## Keep as Reference, Not Immediate Runtime Tools

These have useful ideas but are less urgent or overlap with Hermes-native tooling.

| Tool/group | Reason |
|---|---|
| Case query tools: `get_case_overview`, `get_case_structure`, `get_case_timeline`, `get_case_medical_summary`, `get_case_insurance`, `get_case_liens`, `get_case_providers`, `search_case` | Useful UX patterns, but built on old JSON backend. Current source of truth is FirmVault case folder/wiki/state. Reimplement as FirmVault wiki/state queries instead of porting directly. |
| Workflow tools: `get_case_workflow_status`, `get_workflow_resources`, `advance_phase`, `recalculate_case_phase`, `update_landmark`, `get_statute_status`, `update_statute_status` | Useful phase/landmark ideas, but current workflow model has changed. Extract concepts; do not directly wire until mapped to current `state.yaml` and workflow templates. |
| Calendar tools: old internal and Google Calendar variants | Current Google Workspace DWD skill should own real Calendar. Keep only any case-calendar schema ideas. |
| Slack/email tools: `send_slack_message`, `upload_file_to_slack`, `dispatch_email_task`, `show_unread_emails`, `mark_email_read` | Superseded by Hermes `send_message`, paralegal Gmail DWD heartbeat, and case Slack routing. Keep patterns only. |
| Graph tools: `graph_query`, `query_case_graph`, `write_entity`, `update_entity`, `create_case` | Old graph/JSON assumptions. Useful if we revive graph-backed case intelligence, but not priority while FirmVault/wiki-agent is canonical. |
| UI/template tools: `load_ui_template`, `list_available_templates`, `get_template_info`, `display_document`, `generate_directory_browser` | May help future dashboards; not needed for immediate paralegal automation. |
| Job tools: `dispatch_medical_records_analysis`, `dispatch_case_file_organization`, `check_job`, `list_jobs`, `resume_job`, `remove_job` | Old background-agent system. Useful concepts, but Mission Control/Hermes cron/delegation now own orchestration. |
| `list_skills`, `load_skill`, `refresh_skills` | Old skill loader. Hermes already has `skill_view`, `skills_list`, `skill_manage`. Archive. |
| Internet search tools | Superseded by Hermes `web_search`/`web_extract`; archive unless some result formatting is valuable. |

## Archive / Low Value

| Tool/group | Why |
|---|---|
| `_templates` | Template scaffold only; one Python template has intentional invalid placeholder syntax. Keep in archive, not runtime. |
| Duplicate calendar tools | There are internal graph calendar tools and Google Calendar tools. Avoid duplicate routing. Use Google Workspace DWD for real calendar. |
| Duplicate search tools: `internet_search` / `internet_search_research` | Hermes has better native web search/extract. |
| Legacy email JSON tools | Current direction is Gmail DWD → FirmVault/Slack/Honcho, not JSON inbox tools or Mission Control email task flood. |

## Technical Findings

### Inventory

- `tool.yaml` directories found: **99**
- Python files found under tree: **199**
- Python syntax parse result from quick AST scan: **98/99 ok**
  - only `_templates/tool_template.py` failed, which is expected for a template scaffold.
- Existing legacy validation docs claimed previous status: **79/93 working** at the time of that validation.

### Main breakage points

1. **Old backend path**

   `_shared/json_backend_utils.py` inserts:

   ```text
   /Users/aaronwhaley/RoscoeDesktop/desktop/backend/test_composite_backend
   ```

   and defaults workspace to:

   ```text
   /Volumes/X10 Pro/projects
   ```

   That is old-world. Current tools need a FirmVault resolver:

   ```text
   active case cwd → FirmVault/cases/<slug>
   state.yaml / case markdown / wiki-agent pages / activity logs
   ```

2. **Hardcoded workspace assumptions**

   Many tools are configurable by `workspace`, but default to old paths. They need a shared resolver that respects:

   - `get_turn_cwd()`
   - `TERMINAL_CWD`
   - `FIRMVault_ROOT` / `FIRMVault_CASES_ROOT`
   - paralegal profile cwd/channel case mapping

3. **Old graph assumptions**

   Several tools expect JSON categories or FalkorDB/Graphiti-style graph structures. The current canonical source is FirmVault, with wiki-agent/Honcho as memory/query layers.

4. **Credential/web automation risk**

   eCourts, Lexis, DocuSign, Slack, Google tools need modern secret handling and approval gates. Do not port with embedded `.env` assumptions.

5. **Side effects need policy wrappers**

   Tools that move files, send docs, update statuses, create events, or send Slack/email must be wrapped with dry-run/default-safe behavior.

## Recommended Migration Plan

### Phase 1 — Preserve and index

- Keep `/Volumes/X10 Pro/projects/Tools` as read-only legacy source.
- Copy selected P0/P1 tools into a Hermes/FirmVault migration branch or `legacy_tools/` archive with provenance.
- Preserve inventory JSON:

  ```text
  /Users/aaronwhaley/Github/Roscoe-hermes/reports/legacy_law_tools_inventory.json
  ```

### Phase 2 — Build shared compatibility layer

Create one compatibility module instead of patching paths in 40 files:

```python
resolve_case_root(case_slug=None, cwd=None)
resolve_firmvault_root()
load_case_state(case_slug)
write_case_activity(case_slug, event)
find_case_by_name_or_slug(query)
```

This layer should map old calls like:

```text
cases/<case>/medical.json
```

to current FirmVault structures or wiki/Honcho queries.

### Phase 3 — Port P0 domain tools

Port in this order:

1. `settlement_calculator`
2. `pip_waterfall`
3. `negotiation_tracker`
4. `checkin_tracker`
5. `medical_request_generator`
6. `generate_demand_pdf`
7. `kyecourts_docket` / `kyecourts_download_documents`
8. `read_pdf` / `chronology_tools`

### Phase 4 — Rebuild case query tools against FirmVault

Instead of using old JSON backend, expose Hermes-native tools:

- `get_case_overview_from_firmvault`
- `get_case_medical_summary_from_wiki`
- `get_case_timeline_from_activity_log`
- `get_case_insurance_from_state_and_docs`
- `get_case_workflow_status_from_state`

### Phase 5 — Retire superseded tools

Archive old Slack, Gmail, Google Calendar, web search, and skill loader tools unless they have unique logic worth extracting.

## Full Tool Recommendation Table

| Tool | Category | Recommendation | Notes |
|---|---|---|---|
| `active_negotiations_report` | Reporting | **Port / adapt** | Useful reporting logic; point at FirmVault negotiation state. |
| `advance_phase` | Workflow Management | Reference | Old workflow state; remap to current phase/landmark templates. |
| `analyze_audio` | vision | Port / adapt | Useful for voicemail/audio attachments; use current transcription stack. |
| `analyze_image` | vision | Port / adapt | Useful pattern; Hermes vision may supersede implementation. |
| `analyze_video` | vision | Reference | Lower priority unless case video workflow needs it. |
| `batch_cleanup_markdown` | document_processing | Port / adapt | Useful cleanup after PDF/OCR conversion. |
| `calendar_add_event_internal` | calendar | Archive/reference | Internal graph calendar is not current source. |
| `calendar_delete_event_internal` | calendar | Archive/reference | Superseded. |
| `calendar_list_events_internal` | calendar | Archive/reference | Superseded. |
| `calendar_update_event_internal` | calendar | Archive/reference | Superseded. |
| `case_file_organizer` | case_management | **Port / adapt** | Valuable classification/manifest/apply concepts; must be gated and FirmVault-aware. |
| `check_job` | medical_analysis | Reference | Old job framework; Mission Control/Hermes orchestration supersedes. |
| `checkin_tracker` | client_management | **Port / adapt** | High-value client follow-up workflow. |
| `chronology_tools` | utility | **Port / adapt** | High-value medical chronology logic. |
| `cleanup_markdown` | document_processing | Port / adapt | Useful OCR/PDF markdown cleanup utility. |
| `combine_letter_and_hipaa` | utility | Port / adapt | Useful medical request packaging. |
| `combine_pdfs` | utility | Port / adapt | Useful, but check dependency stack. |
| `complete_calendar_event` | Calendar | Archive/reference | Superseded by Google Workspace DWD / current calendar plan. |
| `copy_file` | file_operations | Archive/reference | Hermes file tools already cover this. |
| `create_calendar_event` | Calendar | Archive/reference | Superseded by Google Workspace DWD. |
| `create_case` | Knowledge Graph | Reference | Old JSON/graph creation; current case creation should create FirmVault repo/folder/state. |
| `create_document_from_template` | templates | Port / adapt | Useful template merge concept; map to current templates. |
| `create_file_inventory` | utility | Port / adapt | Useful FirmVault audit helper. |
| `dispatch_case_file_organization` | medical_analysis | Reference | Old job orchestration; preserve prompts/logic. |
| `dispatch_email_task` | communication | Archive/reference | Do not revive Mission Control email flood. |
| `dispatch_medical_records_analysis` | medical_analysis | Reference | Good workflow concept; orchestration should be Hermes/Mission Control now. |
| `display_document` | file_operations | Archive/reference | UI-specific. |
| `docusign_send` | esignature | Port / adapt later | Useful, but blocked until DocuSign auth/template setup is correct. |
| `docusign_status` | esignature | Port / adapt later | Useful once DocuSign wrapper is modernized. |
| `expert_witness_lookup` | research | Port / adapt | Useful research helper. |
| `explore_citations` | legal_research | Port / adapt | Useful CourtListener citation exploration. |
| `find_my_cases` | legal_research | Port / adapt | Useful attorney docket search. |
| `generate_demand_pdf` | document_processing | **Port / adapt** | High-value demand package tooling. |
| `generate_directory_browser` | file_operations | Reference | Useful for dashboards/inventory, not core. |
| `get_case_insurance` | Case Queries | Rebuild | Rebuild against FirmVault state/wiki. |
| `get_case_liens` | Case Queries | Rebuild | Rebuild against FirmVault liens/docs. |
| `get_case_medical_summary` | Case Queries | Rebuild | Rebuild against wiki-agent/chronology. |
| `get_case_overview` | Case Queries | Rebuild | Rebuild against FirmVault state/wiki. |
| `get_case_providers` | Case Queries | Rebuild | Rebuild against contacts/providers in FirmVault. |
| `get_case_structure` | Case Queries | Rebuild | Rebuild against actual folder tree. |
| `get_case_timeline` | Case Queries | Rebuild | Rebuild against activity log. |
| `get_case_workflow_status` | Workflow Management | Rebuild | Rebuild against current workflow/state model. |
| `get_docket_details` | legal_research | Port / adapt | Useful CourtListener docket detail tool. |
| `get_opinion_full_text` | legal_research | Port / adapt | Useful legal research helper. |
| `get_overdue_tasks` | Calendar | Archive/reference | Superseded by current task/calendar stack. |
| `get_statute_status` | Workflow Management | Rebuild | Current SOL tool exists; compare logic before porting. |
| `get_template_info` | ui_components | Reference | UI helper only. |
| `get_workflow_resources` | Workflow Management | Rebuild/reference | Useful workflow concept; update to current templates. |
| `google_calendar_create_event` | google_calendar | Archive | Use Google Workspace DWD skill. |
| `google_calendar_delete_event` | google_calendar | Archive | Use Google Workspace DWD skill. |
| `google_calendar_list_events` | google_calendar | Archive | Use Google Workspace DWD skill. |
| `google_calendar_update_event` | google_calendar | Archive | Use Google Workspace DWD skill. |
| `graph_query` | knowledge_graph | Reference | Useful if graph layer returns; not immediate. |
| `import_documents` | document_processing | Port / adapt | Useful import/index workflow. |
| `internet_search` | research | Archive | Hermes web tools supersede. |
| `internet_search_research` | research | Archive | Duplicate/superseded. |
| `kyecourts_docket` | web_scraping | **Port / adapt** | High-value KY litigation automation. |
| `kyecourts_download_documents` | web_scraping | **Port / adapt** | High-value KY litigation automation. |
| `lexis_crash_order` | crash_reports | Port / adapt later | Useful for crash reports; needs credentials/approval guard. |
| `list_available_templates` | ui_components | Reference | UI helper. |
| `list_calendar_events` | Calendar | Archive/reference | Superseded. |
| `list_document_templates` | templates | Port / adapt | Useful for document automation. |
| `list_jobs` | medical_analysis | Reference | Old job framework. |
| `list_skills` | research | Archive | Hermes skills supersede. |
| `load_skill` | research | Archive | Hermes skills supersede. |
| `load_ui_template` | ui_components | Reference | UI helper. |
| `mark_email_read` | Email | Archive | Gmail DWD heartbeat supersedes. |
| `medical_request_generator` | document_processing | **Port / adapt** | High-value medical records request workflow. |
| `monitor_upcoming_dates` | legal_research | Port / adapt | Useful litigation monitoring. |
| `move_file` | file_operations | Archive/reference | Hermes file tools cover this; keep only policy ideas. |
| `negotiation_tracker` | negotiation | **Port / adapt** | High-value negotiation state. |
| `oral_arguments_search` | legal_research | Port / adapt | Useful CourtListener research. |
| `outstanding_medical_bills_report` | reporting | Port / adapt | Useful damages/medical balance report. |
| `outstanding_medical_records_report` | reporting | Port / adapt | Useful records follow-up report. |
| `pip_waterfall` | insurance | **Port / adapt** | High-value Kentucky PIP logic. |
| `pubmed_search` | medical_research | Port / adapt | Useful medical research. |
| `query_case_graph` | knowledge_graph | Reference | Old graph layer. |
| `read_multimodal_file` | vision | Port / adapt | Useful for attachments; update to current model/tool APIs. |
| `read_pdf` | document_processing | **Port / adapt** | High-value extraction/caching. |
| `recalculate_case_phase` | Workflow Management | Rebuild/reference | Useful logic, old state model. |
| `refresh_skills` | research | Archive | Hermes skill system supersedes. |
| `remove_job` | medical_analysis | Reference | Old job framework. |
| `resume_job` | job_management | Reference | Old job framework. |
| `search_calendar` | Calendar | Archive/reference | Superseded. |
| `search_case` | Case Queries | Rebuild | Rebuild against FirmVault/wiki. |
| `search_case_law` | legal_research | Port / adapt | Useful CourtListener search. |
| `semantic_scholar_search` | medical_research | Port / adapt | Useful medical research. |
| `send_slack_message` | communication | Archive/reference | Hermes `send_message` supersedes. |
| `settlement_calculator` | settlement | **Port / adapt** | High-value settlement distribution logic. |
| `show_unread_emails` | Email | Archive | Superseded by Gmail DWD heartbeat. |
| `split_large_pdf` | vision | Port / adapt | Useful large PDF handling. |
| `update_calendar_event` | Calendar | Archive/reference | Superseded. |
| `update_entity` | Knowledge Graph | Reference | Old graph/JSON state. |
| `update_landmark` | Workflow Management | Rebuild/reference | Useful concept; old state model. |
| `update_statute_status` | Workflow Management | Rebuild/reference | Compare against current SOL tooling. |
| `upload_file_to_slack` | communication | Archive/reference | Hermes Slack/file delivery should own this. |
| `view_pdf` | vision | Port / adapt | Useful PDF visual review pattern. |
| `write_entity` | Knowledge Graph | Reference | Old graph/JSON state. |
| `_templates` |  | Archive | Scaffold only. |

## Next concrete step

If we want the fastest win, I would port **four pure-domain tools first** because they avoid external auth and are easiest to test:

1. `settlement_calculator`
2. `pip_waterfall`
3. `negotiation_tracker`
4. `checkin_tracker`

Then port the document-heavy tools:

5. `read_pdf`
6. `chronology_tools`
7. `medical_request_generator`
8. `generate_demand_pdf`

The court/DocuSign/web automation tools are valuable, but they should come after the compatibility layer and secret/approval wrappers are in place.
