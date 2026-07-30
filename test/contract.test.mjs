import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const action = await readFile(new URL('../action.yml', import.meta.url), 'utf8');
const skill = await readFile(
  new URL('../skills/follow-up-review.md', import.meta.url),
  'utf8',
);
const example = await readFile(
  new URL('../examples/automatic-review.yml', import.meta.url),
  'utf8',
);

test('action pins upstream code and matching OpenHands packages', () => {
  assert.match(action, /default: 9def413cc05fa8287ed236d846af85f977baea45/);
  assert.match(action, /default: openhands-sdk==1\.39\.0/);
  assert.match(action, /default: openhands-tools==1\.39\.0/);
  assert.equal((action.match(/persist-credentials: false/g) ?? []).length, 2);
  assert.match(action, /enable-cache: \$\{\{ inputs\.enable-uv-cache \}\}/);
});

test('follow-up reviews use a stable marker and explicit classifications', () => {
  assert.match(skill, /<!-- agentic-pr-review -->/);
  assert.match(skill, /\*\*resolved\*\*/);
  assert.match(skill, /\*\*still present\*\*/);
  assert.match(skill, /\*\*obsolete\*\*/);
  assert.match(skill, /Do not post a duplicate inline comment/);
});

test('automatic example reruns on commits without exposing secrets to forks', () => {
  assert.match(example, /synchronize/);
  assert.match(
    example,
    /github\.event\.pull_request\.head\.repo\.full_name == github\.repository/,
  );
  assert.match(example, /continue-on-error: true/);
  assert.match(example, /wende\/agentic-pr-review@v1\.0\.0/);
});
