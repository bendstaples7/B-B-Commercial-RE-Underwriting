#!/usr/bin/env node
/**
 * stop — follow up when live-ui needsFollowup is set (blind UI done / invalid SEEN).
 */
const {
  readStdin,
  writeStdout,
  readState,
  writeState,
} = require('./live-ui-visibility-lib.js');

const FOLLOWUP = [
  'Live-UI visibility enforcement: UI claim without valid authenticated proof.',
  '1. Ensure session: Capture FAB → Export session, or BB_E2E_EMAIL/PASSWORD.',
  '2. Snapshot: npm run live-ui:snapshot --prefix frontend -- --url <path> --selector <css> --label <name>',
  '3. Read the PNG under artifacts/live-ui/.',
  '4. End with:',
  '',
  '### Live-UI',
  'VERDICT: SEEN',
  '- surface: … @ …',
  '- channel: auth-playwright | capture-fab | chromium-session',
  '- artifact: artifacts/live-ui/<file>.png (Read: …)',
  '',
  'or VERDICT: NOT SEEN with blocker (do not ask for human retest while NOT SEEN).',
].join('\n');

(async () => {
  const input = await readStdin();
  const status = String(input.status || '');
  const loopCount = Number(input.loop_count || 0);
  const state = readState();

  if (status !== 'completed' && status !== 'complete') {
    writeStdout({});
    return;
  }

  if (!state.needsFollowup) {
    writeStdout({});
    return;
  }

  if (loopCount >= 3) {
    writeState({
      needsFollowup: false,
      pending: true,
      source: 'stop',
      reason: 'loop_limit_reached',
    });
    writeStdout({});
    return;
  }

  writeState({
    pending: true,
    needsFollowup: true,
    source: 'stop',
    loopCount,
  });

  writeStdout({
    followup_message: FOLLOWUP,
  });
})().catch(() => {
  process.stdout.write('{}');
});
