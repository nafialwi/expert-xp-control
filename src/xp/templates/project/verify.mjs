import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export const canonicalCommands = [
  {label: 'npm run lint', command: 'npm', args: ['run', 'lint']},
  {label: 'npm run typecheck', command: 'npm', args: ['run', 'typecheck']},
  {label: 'npm run test', command: 'npm', args: ['run', 'test']},
  {label: 'npm run build', command: 'npm', args: ['run', 'build']},
];

export function runCanonicalVerify() {
  for (const { label, command, args } of canonicalCommands) {
    console.log(`\n==> ${label}`);
    const result = spawnSync(command, args, {stdio: 'inherit', shell: false});
    if (result.error) throw result.error;
    if (result.status !== 0) process.exit(result.status ?? 1);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runCanonicalVerify();
}
