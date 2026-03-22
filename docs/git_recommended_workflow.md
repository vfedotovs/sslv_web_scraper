# Git Recommended Workflow

## Branching Strategy: GitHub Flow (Simplified)

For a single-developer project, GitHub Flow is the best fit — simple, linear, and easy to maintain.

```
main (protected, always deployable, auto-deploys to EC2)
  └── feature/XXX-short-description   (new functionality)
  └── bugfix/XXX-short-description    (bug fixes)
  └── hotfix/XXX-short-description    (urgent production fixes)
```

## Branch Naming Convention

| Prefix | Use case | Example |
|--------|----------|---------|
| `feature/` | New functionality | `feature/389-add-cron-service` |
| `bugfix/` | Non-urgent bug fixes | `bugfix/391-oom-memory-leak` |
| `hotfix/` | Urgent production fixes | `hotfix/395-ws-crash` |

Rules:
- Always prefix with issue number
- Use lowercase and hyphens
- Keep descriptions short (3-5 words)
- No long-lived integration branches (no `dev-*` branches)

## Workflow Diagram

```
main (protected, auto-deploys to EC2)
│
│ ← v1.5.10 tag
│
├── feature/389-add-cron-service ──── PR #390 ──┐
│                                                │ merge + delete branch
│◄───────────────────────────────────────────────┘
│
│ ← v1.5.11 tag
│
├── bugfix/391-oom-memory-leak ────── PR #392 ──┐
│                                                │ merge + delete branch
│◄───────────────────────────────────────────────┘
│
│ ← v1.5.12 tag
│
├── feature/393-multi-city-scraper ── PR #394 ──┐
│                                                │ merge + delete branch
│◄───────────────────────────────────────────────┘
│
│ ← v1.6.0 tag (new feature = minor bump)
│
│  !! Production is down !!
│
├── hotfix/395-ws-crash ──────────── PR #396 ───┐
│                                                │ merge + delete branch
│◄───────────────────────────────────────────────┘
│
│ ← v1.6.1 tag
│
```

## Workflow Steps

### Feature (new functionality)

```bash
git checkout main && git pull
git checkout -b feature/389-add-cron-service
# ... make commits ...
git push -u origin feature/389-add-cron-service
gh pr create --base main
# Merge PR → CI/CD deploys to EC2
git tag -a v1.5.11 -m "Release 1.5.11"
git push origin v1.5.11
# Branch auto-deleted after merge
```

### Bugfix (non-urgent fix)

```bash
git checkout main && git pull
git checkout -b bugfix/391-oom-memory-leak
# ... make commits ...
git push -u origin bugfix/391-oom-memory-leak
gh pr create --base main
# Merge PR → CI/CD deploys to EC2
git tag -a v1.5.12 -m "Release 1.5.12"
git push origin v1.5.12
# Branch auto-deleted after merge
```

### Hotfix (urgent production fix)

```bash
git checkout main && git pull
git checkout -b hotfix/395-ws-crash
# ... minimal fix, no extras ...
git push -u origin hotfix/395-ws-crash
gh pr create --base main
# Merge PR → CI/CD deploys to EC2
git tag -a v1.6.1 -m "Hotfix 1.6.1"
git push origin v1.6.1
# Branch auto-deleted after merge
```

## Version Bumping Rules (Semver)

```
v1.6.1
  │ │ └── PATCH: bugfix or hotfix (no new features)
  │ └──── MINOR: new feature (backwards compatible)
  └────── MAJOR: breaking change (API/config change)
```

Examples:

| Change | Version bump |
|--------|-------------|
| OOM memory fix | v1.5.12 (patch) |
| Add cron service | v1.6.0 (minor) |
| Change deploy config / breaking API change | v2.0.0 (major) |

## Key Principles

1. **Branch from `main`, PR back to `main`** — no intermediate integration branches
2. **One feature per branch** — keeps PRs small and reviewable
3. **Delete branches after merge** — prevents stale branch accumulation
4. **Tag every release** — every merge to `main` gets a semver tag
5. **Consistent naming** — always use `feature/`, `bugfix/`, or `hotfix/` prefix
6. **CI/CD triggers on merge to `main`** — automated deployment to EC2
