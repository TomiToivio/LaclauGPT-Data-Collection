# Pre-Publication Checklist

Do not change this repository to public until every item below is satisfied.

## 1. Public tree

- `main` contains only code, documentation, schemas and synthetic examples.
- `python scripts/check_public_tree.py` passes.
- CI passes.
- There are no real datasets, target lists, browser profiles, cookies or operational configs in the current tree.

## 2. Git references

History cleanup is not complete merely because `main` was force-pushed.

Verify all repository refs. Branches and tags pointing into the pre-cleanup history must be removed or rewritten.

This repository had a historical merged pull request (`#1`) before the public-history reset. GitHub maintains read-only `refs/pull/*` references separately from normal branches. If `refs/pull/1/head` still points to a pre-cleanup commit, **do not make the repository public**.

GitHub's documented sensitive-data removal process states that pull-request refs cannot be removed by a normal mirror/force push. For sensitive material, GitHub Support can dereference affected PRs, remove cached views and run server-side garbage collection after the normal refs have been cleaned. If the old material is private but does not qualify for GitHub Support's sensitive-data process, the safest publication path is a newly created repository with only the reviewed public root commit.

## 3. Credentials

Any credential that ever entered Git must be rotated/revoked even if history is rewritten.

## 4. Clones and forks

Old clones or forks can reintroduce removed history. Re-clone after the reset rather than merging old history back into the cleaned repository.

## 5. Final verification

Before changing visibility:

- inspect `https://api.github.com/repos/TomiToivio/LaclauGPT-Data-Collection/git/refs` while the repo is private;
- verify no branch/tag points at old history;
- resolve any old `refs/pull/*` publication blockers;
- confirm CI is green on the rewritten `main`;
- verify repository visibility is still private until these checks are complete.
