---
id: history
title: Git history and source comparisons
description: Save source versions, preview changes and restore through private local Git history.
section: Edit and rebuild
parent: projects
order: 8
revision: 2
---

**Project IDE → Git history** stores private local source versions. Git must be installed and available on PATH. This history is separate from any existing Git repository in the attached source folder and separate from CyDecompilator's own development repository.

## Save and compare {#save-and-compare}

1. Save open files so the disk state matches the intended source version.
2. Enter a meaningful description and choose **Save Git version**.
3. Edit the source or resources, then select a saved version.
4. Choose **Compare with saved sources**, then select a changed file. The shared diff view provides side-by-side changes, next-change navigation and text search. Raw text is available for copying.

```image
{"id": "git-history-screenshot", "src": "assets/git-history.png", "alt": "An actual private Git snapshot compared with modified C++ source in the integrated diff viewer.", "title": "An actual private Git snapshot compared with modified C++ source in the integrated diff viewer.", "controls": "minimal"}
```


## Restore deliberately {#restore-deliberately}

Review the comparison and save pending editor buffers before choosing **Restore this version**. Restoration first saves the current state in a recoverable commit, then records the restored state as another commit. Open files are reloaded. Source-revision checks refuse a restore whose preview no longer matches the files. A restore is not a silent reset of the source folder's own repository.

## What is included {#what-is-included}

Sources, resources and local dependencies within the workspace are versioned according to the history rules. Build folders, caches and Git metadata are excluded. Binary files can be saved, but their differences are not shown as text. Snapshot limits are 4,000 files, 128 MiB total and 32 MiB per file; exceeding them needs a smaller source scope, not unlimited automatic copying.

Automated reconstruction repairs also record Git backups. A modified managed copy can show its source commit when an appropriate snapshot existed before patch creation. A source snapshot does not back up every installed engine, original game asset or external runtime.

## Backup and recovery {#backup-and-recovery}

Preserve the project's data/history directory together with its sources when moving or backing up an installation. Do not delete a project to clear a build cache: that may remove its private history and recorded evidence. See [storage](doc:storage) for directory roles and [reconstruction](doc:reconstruction) for source-repair workflows.
