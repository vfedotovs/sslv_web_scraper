# GitHub Workflows TODO

## Current State — 8 workflow files, most are obsolete

| File | Triggers | Deploys to | Status |
|------|----------|-----------|--------|
| `main.yml` | Push to `main` (`.py` files) | **Prod EC2** (`PROD_M5_EC2_*`) | **Active — the only one that matters** |
| `CICD-dev-1.5.10.yml` | Push to `dev-1.5.8/9/10` | **Dev EC2** (`DEV_EC2_*`) | Obsolete — branches are merged |
| `CICD-dev-1.5.3.yml` | Push to `dev-1.5.3/4/8/9` | **Dev EC2** (`DEV_EC2_*`) | Obsolete — branches are merged |
| `CICD-dev-1412.yml` | Push to `dev-1.4.12` | **Dev EC2** (`DEV_EC2_*`) | Obsolete — branch is merged |
| `CICD-arm-dev-m5.yml` | Manual only | **M5 EC2** (`M5_EC2_*`) | Obsolete — manual trigger, hardcoded `dev-1.5.8` checkout |
| `CICD-arm-dev-1.5.x.yml` | Manual only | None (test only) | Obsolete — duplicate of `CICD-arm-m5.yml` |
| `CICD-arm-m5.yml` | Manual only | None (test only) | Obsolete — duplicate |
| `CI.yml` | Push to `dev-1.4*.*` | None (test+build only) | Obsolete — v1.4 is ancient |

## Issues Found

### 1. Hardcoded branch names in deploy steps

- `CICD-arm-dev-m5.yml:138` — `git switch dev-1.5.8` (hardcoded)
- `CICD-dev-1.5.3.yml:130` — `git switch dev-1.5.8` (hardcoded, doesn't even match the file name)
- `CICD-dev-1412.yml:118` — `git switch dev-1.4.12` (hardcoded)
- `CICD-dev-1.5.10.yml:129` — `git switch dev-1.5.10` (hardcoded)

### 2. Legacy `docker-compose` vs modern `docker compose`

- `CI.yml` — uses `docker-compose` (legacy)
- `CICD-dev-1412.yml` — uses `docker-compose` (legacy)
- `CICD-dev-1.5.3.yml` — mixed (`docker compose` in build, `docker-compose` in deploy)
- `CICD-dev-1.5.10.yml` — mixed (`docker compose` in build, `docker-compose` in deploy)
- `main.yml` — no docker compose calls (deploys via SSH)

### 3. Deprecated SENDGRID_API_KEY references

- `CI.yml:63`
- `CICD-dev-1412.yml:60`
- `CICD-dev-1.5.3.yml:70`
- `CICD-dev-1.5.10.yml:70`
- `CICD-arm-dev-m5.yml:46/63`

All still reference `SENDGRID_API_KEY` which is no longer used (replaced by AWS SES).

### 4. Inconsistent action versions

- `actions/checkout` — mix of `@v3` and `@v4`
- `actions/setup-python` — mix of `@v2` and `@v5`
- `codecov/codecov-action` — mix of `@v3` and `@v4`

### 5. Security concern — secrets printed to logs

- `cat src/ws/database.ini` and `cat .env.prod` in multiple workflows prints credentials to GitHub Actions logs

## Recommended EC2 Setup — 2 instances

```
┌─────────────────────────────────────────────────────┐
│  EC2 #1: STAGING                                    │
│  Purpose: Test branches before merging to main      │
│  Trigger: Manual (workflow_dispatch) or on PR        │
│  Lifetime: Always running                           │
│                                                     │
│  Workflow:                                          │
│  1. Push to feature/bugfix/hotfix branch            │
│  2. Create PR → staging workflow deploys to EC2 #1  │
│  3. Run for multiple days to verify stability       │
│  4. If stable → merge PR to main                    │
└─────────────────────────────────────────────────────┘
                        │
                        │ PR merged after multi-day test
                        ▼
┌─────────────────────────────────────────────────────┐
│  EC2 #2: PRODUCTION                                 │
│  Purpose: Serves live traffic                       │
│  Trigger: Automatic on push to main (**.py)         │
│  Lifetime: Always running                           │
│                                                     │
│  Workflow:                                          │
│  1. PR merged to main                               │
│  2. main.yml auto-deploys to EC2 #2                 │
│  3. Tag release version                             │
└─────────────────────────────────────────────────────┘
```

## Target State — 2 workflow files

| File | Purpose |
|------|---------|
| `main.yml` | Auto-deploy to **production** EC2 on push to `main` |
| `staging.yml` (new) | Deploy to **staging** EC2 on `workflow_dispatch` or PR creation |

## Action Items

- [ ] Create `staging.yml` workflow for staging EC2 deployments
- [ ] Update `main.yml` to remove SENDGRID_API_KEY references
- [ ] Update `main.yml` to not print secrets to logs
- [ ] Delete 6 obsolete workflow files:
  - [ ] `CI.yml`
  - [ ] `CICD-dev-1412.yml`
  - [ ] `CICD-dev-1.5.3.yml`
  - [ ] `CICD-dev-1.5.10.yml`
  - [ ] `CICD-arm-dev-1.5.x.yml`
  - [ ] `CICD-arm-m5.yml`
- [ ] Standardize on `actions/checkout@v4`, `actions/setup-python@v5`, `codecov/codecov-action@v4`
- [ ] Use `docker compose` (v2) everywhere, remove legacy `docker-compose`
- [ ] Set up staging EC2 instance with matching secrets/env vars
