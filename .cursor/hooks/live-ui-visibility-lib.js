/**
 * Shared state + helpers for live-ui-visibility Cursor hooks.
 */
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const STATE_PATH = path.join(
  process.env.USERPROFILE || process.env.HOME || '',
  '.cursor',
  'hooks',
  'state',
  'live-ui-visibility.json'
);

function readState() {
  try {
    if (!fs.existsSync(STATE_PATH)) {
      return { pending: false, needsFollowup: false };
    }
    return {
      pending: false,
      needsFollowup: false,
      ...JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')),
    };
  } catch {
    return { pending: false, needsFollowup: false };
  }
}

function writeState(next) {
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  fs.writeFileSync(
    STATE_PATH,
    JSON.stringify({ ...readState(), ...next, updatedAt: new Date().toISOString() }, null, 2)
  );
}

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => {
      try {
        resolve(data.trim() ? JSON.parse(data) : {});
      } catch {
        resolve({});
      }
    });
  });
}

function writeStdout(obj) {
  process.stdout.write(JSON.stringify(obj));
}

function findRepoRoot(cwd) {
  let dir = cwd || process.cwd();
  for (let i = 0; i < 14; i += 1) {
    if (
      fs.existsSync(path.join(dir, 'scripts', 'live-ui', 'claim-guard.mjs'))
    ) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function isFrontendUiPath(filePath) {
  const p = String(filePath || '').replace(/\\/g, '/');
  if (!/frontend\//i.test(p)) return false;
  return /frontend\/src\/.+\.(tsx?|jsx?|css)$/i.test(p);
}

/**
 * Run claim-guard.mjs --check-claim with payload.
 */
function runClaimGuard({ text, repoRoot, pending }) {
  const guard = path.join(repoRoot, 'scripts', 'live-ui', 'claim-guard.mjs');
  const payload = JSON.stringify({
    text: text || '',
    repoRoot,
    pending: Boolean(pending),
  });
  const r = spawnSync(process.execPath, [guard, '--check-claim'], {
    cwd: repoRoot,
    encoding: 'utf8',
    input: payload,
    timeout: 15000,
  });
  let result = null;
  try {
    result = JSON.parse(String(r.stdout || '').trim() || '{}');
  } catch {
    result = {
      ok: r.status === 0,
      action: r.status === 0 ? 'none' : 'followup',
      reason: 'claim_guard_parse_error',
      message: String(r.stderr || r.stdout || '').slice(0, 500),
    };
  }
  return { status: r.status, result };
}

module.exports = {
  STATE_PATH,
  readState,
  writeState,
  readStdin,
  writeStdout,
  findRepoRoot,
  isFrontendUiPath,
  runClaimGuard,
};
