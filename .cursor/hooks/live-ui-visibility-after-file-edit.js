#!/usr/bin/env node
/**
 * afterFileEdit — arm live-ui pending when frontend/src UI files change.
 */
const {
  readStdin,
  writeStdout,
  readState,
  writeState,
  isFrontendUiPath,
} = require('./live-ui-visibility-lib.js');

(async () => {
  const input = await readStdin();
  const file =
    input.file ||
    input.path ||
    input.filePath ||
    input.uri ||
    (Array.isArray(input.edits) && input.edits[0]?.path) ||
    '';

  if (!isFrontendUiPath(file)) {
    writeStdout({});
    return;
  }

  writeState({
    pending: true,
    needsFollowup: false,
    source: 'afterFileEdit',
    lastFile: String(file),
    reason: 'frontend_src_edit',
  });
  writeStdout({});
})().catch(() => {
  process.stdout.write('{}');
});
