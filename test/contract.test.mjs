import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import test from 'node:test';

const execFileAsync = promisify(execFile);
const action = await readFile(new URL('../action.yml', import.meta.url), 'utf8');
const skill = await readFile(
  new URL('../skills/follow-up-review.md', import.meta.url),
  'utf8',
);
const installGuidance = fileURLToPath(
  new URL('../scripts/install-guidance.sh', import.meta.url),
);
const followupSkillPath = fileURLToPath(
  new URL('../skills/follow-up-review.md', import.meta.url),
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

test('plain repository guidance is wrapped as a codereview skill', () => {
  assert.match(action, /review-guidance-path:/);
  assert.match(action, /scripts\/install-guidance\.sh/);
});

test('guidance installer wraps plain Markdown and rejects escaping symlinks', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agentic-review-'));
  const repo = join(root, 'repo');
  const outside = join(root, 'outside.md');
  await mkdir(join(repo, 'docs'), { recursive: true });
  await writeFile(join(repo, 'docs', 'review.md'), '- Check invariants.\r\n');
  await writeFile(outside, 'outside');

  try {
    await execFileAsync(installGuidance, [
      repo,
      followupSkillPath,
      'docs/review.md',
    ]);
    const wrapped = await readFile(
      join(repo, '.agents/skills/repository-review-best-practices.md'),
      'utf8',
    );
    assert.match(wrapped, /name: repository-review-best-practices/);
    assert.match(wrapped, /  - \/codereview/);
    assert.match(wrapped, /- Check invariants\.\n/);

    await symlink(outside, join(repo, 'docs', 'escape.md'));
    await assert.rejects(
      execFileAsync(installGuidance, [
        repo,
        followupSkillPath,
        'docs/escape.md',
      ]),
      (error) => {
        assert.match(
          `${error.stdout ?? ''}${error.stderr ?? ''}`,
          /resolves outside the consumer repository/,
        );
        return true;
      },
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
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
