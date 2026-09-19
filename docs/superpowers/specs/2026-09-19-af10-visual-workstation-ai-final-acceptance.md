# AF-10 — Visual Workstation & AI Final Acceptance

Status: LOCKED IMPLEMENTATION SPEC

Canonical entry baseline:
`f2d8865890ffc141bbada0e0d5c206fd572424fa`

Canonical branch:
`work/xp-plus-v1`

Implementation branch:
`work/af10-visual-final-acceptance`

## Stability-first scope

AF-10 must not destabilize the mature terminal CLI or execution engine.

Therefore AF-10:
- does not redesign `src/xp/cli.py`;
- does not replace `src/xp/ui.py`;
- adds an optional local-only visual workstation surface;
- uses only Python standard library + static HTML/CSS/JS;
- binds to loopback only;
- adds no cloud dependency;
- adds no background provider probe;
- adds no background model switching;
- adds no deployment or database capability.

The terminal CLI remains authoritative and continues to be protected by the
full regression suite.

## Visual surfaces

The local PWA must expose:
- project / checkpoint;
- recovery status;
- current mode;
- AI provider / model;
- cost state;
- worker;
- permission;
- Activity Trail;
- approval;
- verification outcome;
- recovery / rollback;
- LIVE vs LOCAL/OFFLINE state.

The visual snapshot is a projection of observable state only. It must not
persist prompts, model outputs, hidden reasoning, secrets, or arbitrary
Activity Trail metadata.

## Final AI acceptance

AF-10 acceptance proves:
- existing CLI regression remains green;
- OFFLINE remains local;
- ANALYSIS explicit route works;
- WORKER remains approval-governed;
- LIVE remains explicit;
- provider/model identity is visible;
- no silent fallback remains locked;
- AF-09 recovery/rollback semantics remain green;
- Activity Trail projection is safe;
- local PWA assets and status API work over loopback;
- service worker and manifest are present for install/offline static shell.

A successful cloud inference is not an AF-10 closure dependency. AF-05 already
proved real inference; AF-08 proved formal route policy; AF-09 proved real
project orchestration in an isolated project copy.

## Stable promotion boundary

AF-10 completion does NOT mean XP+ Stable.

After AF-10 the locked platform gates remain:
1. XP+-07 Universal Acceptance;
2. XP+-08 Release Candidate;
3. XP+-09 Stable;
4. XP+-10 GitHub Release Sync.

Stable may only be declared after those platform gates pass.
