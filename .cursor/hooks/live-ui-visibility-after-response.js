#!/usr/bin/env node
/**
 * afterAgentResponse — veto blind UI done / invalid Live-UI SEEN claims.
 */
const {
  readStdin,
  writeStdout,
  readState,
  writeState,
  findRepoRoot,
  runClaimGuard,
} = require('./live-ui-visibility-lib.js');

(async () => {
  const input = await readStdin();
  const text = String(input.text || input.response || input.message || '');
  const state = readState();

  const workspace =
    input.workspace_roots?.[0] ||
    input.workspaceRoot ||
    input.cwd ||
    process.env.CURSOR_PROJECT_DIR ||
    process.cwd();
  const repo = findRepoRoot(workspace);

  if (!repo) {
    if (/VERDICT:\s*SEEN\b/i.test(text) || /###\s*Live-UI\b/i.test(text)) {
      writeState({
        pending: true,
        needsFollowup: true,
        source: 'afterAgentResponse',
        reason: 'repo_root_missing',
      });
      writeStdout({
        additional_context:
          'STOP: Live-UI claim but scripts/live-ui/claim-guard.mjs not found in workspace.',
      });
      return;
    }
    writeStdout({});
    return;
  }

  const { result } = runClaimGuard({
    text,
    repoRoot: repo,
    pending: state.pending,
  });

  if (result.action === 'clear') {
    writeState({
      pending: false,
      needsFollowup: false,
      source: 'afterAgentResponse',
      lastVerdict: 'SEEN',
      reason: null,
      citedPng: result.citedPng || null,
    });
    writeStdout({});
    return;
  }

  if (result.action === 'followup') {
    writeState({
      pending: true,
      needsFollowup: true,
      source: 'afterAgentResponse',
      reason: result.reason || 'live_ui_followup',
    });
    writeStdout({
      additional_context:
        result.message ||
        'STOP: Live-UI enforcement failed. Run snapshot and emit ### Live-UI VERDICT: SEEN with artifact path.',
    });
    return;
  }

  writeStdout({});
})().catch(() => {
  process.stdout.write('{}');
});
