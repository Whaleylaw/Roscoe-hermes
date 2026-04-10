#!/usr/bin/env node
/**
 * GSD Bridge — thin Node.js wrapper called by the Python daemon adapter.
 *
 * Usage:  node gsd_bridge.mjs <command> < input.json
 * Output: JSON to stdout
 *
 * Commands:
 *   health_check   — verify GSD package is importable
 *   poll_project    — check a project's state, return dispatchable tasks
 *   dispatch_wave   — dispatch a wave of tasks via GSD dispatcher
 *   update_status   — update a task's status in STATE.md
 *   list_projects   — list all discovered GSD projects
 */

import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { readdirSync, existsSync } from 'node:fs';

const GSD_PACKAGE_DIR = process.env.GSD_PACKAGE_DIR || '/opt/data/gsd-lawyerinc';
const GSD_PROJECTS_DIR = process.env.GSD_PROJECTS_DIR || '/opt/data/projects';

/** Dynamic import of GSD library */
let gsd = null;
async function loadGSD() {
  if (gsd) return gsd;
  const indexPath = join(GSD_PACKAGE_DIR, 'src', 'index.js');
  gsd = await import(indexPath);
  return gsd;
}

/** Read JSON from stdin */
async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString().trim();
  return raw ? JSON.parse(raw) : {};
}

/** Write JSON to stdout and exit */
function respond(data) {
  process.stdout.write(JSON.stringify(data) + '\n');
  process.exit(0);
}

// ─── Commands ─────────────────────────────────────────────────────────────────

async function healthCheck() {
  const t0 = Date.now();
  try {
    await loadGSD();
    respond({ ok: true, latency_ms: Date.now() - t0 });
  } catch (err) {
    respond({ ok: false, latency_ms: Date.now() - t0, error: err.message });
  }
}

async function listProjects() {
  const projects = [];
  if (!existsSync(GSD_PROJECTS_DIR)) {
    respond({ ok: true, projects: [] });
    return;
  }

  for (const entry of readdirSync(GSD_PROJECTS_DIR, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const stateFile = join(GSD_PROJECTS_DIR, entry.name, '.planning', 'STATE.md');
    if (existsSync(stateFile)) {
      projects.push({ name: entry.name, path: join(GSD_PROJECTS_DIR, entry.name) });
    }
  }
  respond({ ok: true, projects });
}

async function pollProject(args) {
  const { project, projectPath } = args;
  const lib = await loadGSD();

  const planningDir = join(projectPath || join(GSD_PROJECTS_DIR, project), '.planning');
  const stateFile = join(planningDir, 'STATE.md');

  // 1. Read state
  let state;
  try {
    state = await lib.readState(stateFile);
  } catch (err) {
    respond({ ok: false, error: `Cannot read STATE.md: ${err.message}` });
    return;
  }

  const lifecycle = state.lifecycle || state.meta?.lifecycle || '';

  // Only process projects in EXECUTE lifecycle
  if (lifecycle !== 'EXECUTE') {
    respond({ ok: false, lifecycle, action: 'idle', reason: `Lifecycle is ${lifecycle}, not EXECUTE` });
    return;
  }

  // 2. Find the current phase's PLAN.md
  const currentPhase = state.phase || state.meta?.phase || '';
  const currentWave = state.wave || state.meta?.wave || 1;

  // Look for PLAN.md in phase dir or root .planning
  const planPaths = [
    join(planningDir, 'phases', currentPhase, 'PLAN.md'),
    join(planningDir, 'PLAN.md'),
  ];

  let planFile = null;
  for (const p of planPaths) {
    if (existsSync(p)) { planFile = p; break; }
  }

  if (!planFile) {
    respond({ ok: false, lifecycle, action: 'idle', reason: 'No PLAN.md found' });
    return;
  }

  // 3. Parse the plan
  let plan;
  try {
    plan = await lib.parsePlanFile(planFile);
  } catch (err) {
    respond({ ok: false, error: `Cannot parse PLAN.md: ${err.message}` });
    return;
  }

  if (!plan.tasks || plan.tasks.length === 0) {
    respond({ ok: false, lifecycle, action: 'idle', reason: 'No tasks in PLAN.md' });
    return;
  }

  // 4. Check wave completion status
  const waveComplete = lib.isWaveComplete(state, plan.tasks.filter(t => t.wave === currentWave));

  // 5. Find tasks needing approval
  const needsApproval = [];
  for (const task of plan.tasks) {
    const taskStatus = state.taskStatuses?.[task.id] || '';
    if (task.approval === 'aaron' && taskStatus === 'reviewing') {
      needsApproval.push(taskToJSON(task));
    }
  }

  if (needsApproval.length > 0) {
    respond({
      ok: true,
      lifecycle,
      action: 'needs_approval',
      wave: currentWave,
      tasks: needsApproval,
    });
    return;
  }

  if (waveComplete) {
    // Find next wave
    const waves = lib.groupByWave(plan.tasks);
    const waveNumbers = [...waves.keys()].sort((a, b) => a - b);
    const currentIdx = waveNumbers.indexOf(currentWave);

    if (currentIdx < waveNumbers.length - 1) {
      // Next wave exists — dispatch it
      const nextWave = waveNumbers[currentIdx + 1];
      const nextWaveTasks = waves.get(nextWave) || [];

      respond({
        ok: true,
        lifecycle,
        action: 'dispatch_wave',
        wave: nextWave,
        tasks: nextWaveTasks.map(taskToJSON),
      });
      return;
    } else {
      // All waves complete — advance lifecycle
      respond({
        ok: true,
        lifecycle,
        action: 'advance_lifecycle',
        next_lifecycle: 'VERIFY',
      });
      return;
    }
  }

  // Wave not complete — check if we need to dispatch current wave
  const currentWaveTasks = plan.tasks.filter(t => t.wave === currentWave);
  const undispatched = currentWaveTasks.filter(t => {
    const st = state.taskStatuses?.[t.id] || 'planned';
    return st === 'planned';
  });

  if (undispatched.length > 0) {
    respond({
      ok: true,
      lifecycle,
      action: 'dispatch_wave',
      wave: currentWave,
      tasks: undispatched.map(taskToJSON),
    });
    return;
  }

  // Everything dispatched, waiting for completion
  respond({
    ok: true,
    lifecycle,
    action: 'idle',
    wave: currentWave,
    reason: `Wave ${currentWave} in progress — ${currentWaveTasks.length} tasks dispatched, waiting for completion`,
  });
}

async function dispatchWave(args) {
  const { project, projectPath, wave, tasks, dryRun } = args;
  const lib = await loadGSD();

  // Parse tasks and dispatch
  const results = await lib.dispatchByWaves(tasks, {
    dryRun: dryRun || false,
    stopOnWaveFailure: true,
  });

  // Update STATE.md with dispatched statuses
  const planningDir = join(projectPath || join(GSD_PROJECTS_DIR, project), '.planning');
  const stateFile = join(planningDir, 'STATE.md');

  try {
    await lib.updateState(stateFile, (state) => {
      for (const waveResult of results) {
        for (const r of waveResult.results) {
          if (r.success) {
            lib.setTaskStatus(state, r.taskId, 'dispatched');
          }
        }
      }
      return state;
    });
  } catch (err) {
    // Best effort — log but don't fail
    process.stderr.write(`Warning: failed to update STATE.md: ${err.message}\n`);
  }

  respond({
    ok: true,
    waveResults: results,
  });
}

async function updateStatus(args) {
  const { project, taskId, status } = args;
  const lib = await loadGSD();

  const planningDir = join(GSD_PROJECTS_DIR, project, '.planning');
  const stateFile = join(planningDir, 'STATE.md');

  try {
    await lib.updateState(stateFile, (state) => {
      lib.setTaskStatus(state, taskId, status);
      lib.recomputeMetrics(state);
      return state;
    });
    respond({ ok: true });
  } catch (err) {
    respond({ ok: false, error: err.message });
  }
}

/** Convert a parsed Task to a plain JSON-safe object */
function taskToJSON(task) {
  return {
    id: task.id,
    type: task.type || 'general',
    assignee: task.assignee || '',
    wave: task.wave || 1,
    title: task.title || '',
    description: task.description || '',
    approval: task.approval || '',
    verify: task.verify || '',
    done: task.done || '',
  };
}

// ─── Main ─────────────────────────────────────────────────────────────────────

const command = process.argv[2];
const args = await readStdin();

switch (command) {
  case 'health_check':
    await healthCheck();
    break;
  case 'list_projects':
    await listProjects();
    break;
  case 'poll_project':
    await pollProject(args);
    break;
  case 'dispatch_wave':
    await dispatchWave(args);
    break;
  case 'update_status':
    await updateStatus(args);
    break;
  default:
    respond({ ok: false, error: `Unknown command: ${command}` });
}
