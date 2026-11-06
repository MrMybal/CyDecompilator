---
id: storage
title: Storage, backups and original files
description: Distinguish originals, generated projects, caches and recoverable backups.
section: Settings and reference
parent: settings
order: 19
revision: 2
---

Large applications and console inputs can consume far more disk space than the CyDecompilator code. Inspect free space before extraction, conversion or repeated test copies. Cancelling a job does not imply that every persistent output or partial download has been removed.

## Understand directory ownership {#understand-directory-ownership}

| Location | Contents | Preservation |
|---|---|---|
| Original input location | Your application, resources or archive | Keep as the independent original |
| data/projects/ | Imported snapshots, analysis, editable sources, history and receipts | Persistent project data; back up intentionally |
| data/settings/ | Interface and application settings | Preserve during updates |
| data/jobs/ and reports | Task state, outputs and evidence | Check references before removing old work |
| runtime/python/ | Private interpreter/dependencies | Needed to launch; not a disposable build cache |
| runtime/engines/ | Installed optional tools | Separate from one project's build |
| runtime/build/, downloads, staging/backups | Generated work, downloads, update material | Review exact subdirectory and active use |
| dist/ | Prepared distribution archives | Separate from running projects |

```diagram
{"type": "flow", "title": "Preserve each useful stage", "nodes": [{"id": "step-0", "label": "1. Original input", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Analysis project", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Editable sources", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Git snapshot", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Tested output", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Review cleanup", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Original input** — Keep the independent original.
2. **Analysis project** — Store identity and recovered evidence.
3. **Editable sources** — Know which folder owns the files.
4. **Git snapshot** — Back up meaningful source changes.
5. **Tested output** — Keep the useful artifact and receipt.
6. **Review cleanup** — Remove only identified unused work.


## Avoid unnecessary duplication {#avoid-unnecessary-duplication}

Use existing compatible engines rather than copying a full toolchain for each test. Registering an existing native project can keep a dependency on its current location; know which folder owns its resources. A whole application folder, extracted archive, conversion output and fresh test copy can each occupy significant space. Source-history limits do not bound all of these copies.

## Clean deliberately {#clean-deliberately}

Stop related jobs and inspect the exact directory before removing generated build output, obsolete test captures or old downloads. Preserve the latest useful output, reports required for validation, source-history repositories, original inputs and active runtime components. Deleting a project's data can also delete editable sources and history; it is not equivalent to cleaning compiler objects.

Back up sources, persistent project data and necessary external dependencies together. A Git source snapshot is useful but does not contain every game asset, installed runtime or provider configuration. No documentation button automatically deletes files or starts cleanup.
