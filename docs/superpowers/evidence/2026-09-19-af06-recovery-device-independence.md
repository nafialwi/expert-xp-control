# AF-06 Recovery & Device Independence — Final Evidence

Date: 2026-09-19

- Branch: `work/af06-recovery-device-independence`
- Repository: `nafialwi/expert-xp-control`
- AF-05 base: `a8aab71b35fedc88765a09d21d82cdce5cdf5b66`
- Task 5 baseline: `fe278703e565dc57df4ecc44620ed3e479420ca4`
- Task 6 commit: `2fc70790001be144a3de1f14bc51d250b2b1231c`
- Task 7 commit: `e8f3e52b58c696f3e1e4ee15000353f6de05d332`
- Implementation HEAD before evidence: `e8f3e52b58c696f3e1e4ee15000353f6de05d332`

Verified:
- portable recovery manifest;
- export bundle;
- import/checksum/path/secret verification;
- device-independent restore;
- canonical GitHub reconstruction;
- real fresh-device GitHub reconstruction + state restore;
- full Python regression.

Safety:
- canonical source = repo_slug + branch + commit_sha;
- no device-bound path/id as portable authority;
- bundle verified before restore;
- exact commit/branch reconstruction;
- no credential embedded in canonical GitHub URL;
- no production deployment or database migration.

AF06_STATUS=CLOSED_VERIFIED
NEXT=AF07_GOVERNED_EXECUTION_AND_WORKER_SAFETY
