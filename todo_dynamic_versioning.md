# Dynamic Versioning — Action Items
Generated: 2026-05-02

---

## Current state

`aws_mailer.py:75` has `release = "1.5.10"` hardcoded.
`aws_mailer.py:76` has `RELEASE_VERSION = os.environ['RELEASE_VERSION']` commented out.
`docker-compose.yml:25` already passes `RELEASE_VERSION: ${RELEASE_VERSION}` to the `ws`
container — so the env-var plumbing exists but the value is never injected by the
deployment scripts.

---

## Versioning naming convention

### On an exact release tag (e.g. `v1.5.12`)
```
v1.5.12
```
Used when HEAD == a git tag. This is what production deployments from a tagged release
should show.

### When commits exist past the last tag
```
v1.5.13-rc
```
Derived by bumping the patch number of the last tag and appending `-rc`.
Used when there are merged PRs that are not yet tagged. Both production deploys from
`main` between releases and all staging deploys will show this form.

### Why not use raw `git describe` output (`v1.5.12-3-gabcdef1`)?
Raw git describe is precise but unreadable in an email subject. The `-rc` suffix is
immediately understandable and signals "unreleased work".

### Environment label in email
Append `[production]` or `[staging]` to the subject so the reader knows at a glance
which environment generated the report.

**Subject examples:**
```
Ogre City Apartments for sale from ss.lv web_scraper_v1.5.12_20260502_1330 [production]
Ogre City Apartments for sale from ss.lv web_scraper_v1.5.13-rc_20260502_1330 [staging]
```

---

## Action items

### CI-1: Compute `RELEASE_VERSION` in main.yml (production deploy)
**File**: `.github/workflows/main.yml` — Deploy job, before the SSH block

Add a step that calculates the version from git tags and writes it into the `.env` file
that `docker-compose` reads on the EC2 instance. Because the deploy clones a fresh repo
on the EC2 host, the calculation must happen on the runner (where git history is available)
and the result must be passed to the server.

```yaml
- name: Compute release version
  id: version
  run: |
    git fetch --tags
    LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
    COMMITS_SINCE=$(git rev-list "${LATEST_TAG}..HEAD" --count)
    if [ "$COMMITS_SINCE" = "0" ]; then
      echo "release_version=${LATEST_TAG}" >> "$GITHUB_OUTPUT"
    else
      MAJOR=$(echo "$LATEST_TAG" | sed 's/v//' | cut -d. -f1)
      MINOR=$(echo "$LATEST_TAG" | cut -d. -f2)
      PATCH=$(echo "$LATEST_TAG" | cut -d. -f3)
      NEXT_PATCH=$((PATCH + 1))
      echo "release_version=v${MAJOR}.${MINOR}.${NEXT_PATCH}-rc" >> "$GITHUB_OUTPUT"
    fi
```

Then pass it to the SSH deploy step as an env var:
```yaml
- name: Deploy to Production EC2
  env:
    HOSTNAME: ${{ secrets.PROD_M5_EC2_IP }}
    USER_NAME: ${{ secrets.PROD_USER_NAME }}
    RELEASE_VERSION: ${{ steps.version.outputs.release_version }}
    APP_ENV: production
  run: |
    ssh ... <<EOF
      ...
      echo "RELEASE_VERSION=${RELEASE_VERSION}" >> .env
      echo "APP_ENV=${APP_ENV}" >> .env
      make up
    EOF
```

### CI-2: Add `APP_ENV` to docker-compose.yml
**File**: `docker-compose.yml`

Add `APP_ENV` to the `ws` service environment block alongside `RELEASE_VERSION`:
```yaml
ws:
  environment:
    RELEASE_VERSION: ${RELEASE_VERSION}
    APP_ENV: ${APP_ENV}
```

### CI-3: Same version calculation in staging.yml
**File**: `.github/workflows/staging.yml`

Repeat the same `Compute release version` step. Set `APP_ENV=staging` instead of
`APP_ENV=production`. The version will show `-rc` for most staging deploys since
staging is typically used before tagging a release.

### CODE-1: Uncomment `RELEASE_VERSION` env-var read in `aws_mailer.py`
**File**: `src/ws/app/wsmodules/aws_mailer.py:75-76`

Replace the hardcoded value with the env var, with a safe fallback:
```python
# Before:
release = "1.5.10"
# RELEASE_VERSION = os.environ['RELEASE_VERSION']

# After:
release = os.environ.get('RELEASE_VERSION', 'unknown')
```
Using `.get()` with a fallback means local development without the env var set does
not crash — it just shows `unknown` in the subject.

### CODE-2: Add `APP_ENV` to the email subject in `gen_subject_title()`
**File**: `src/ws/app/wsmodules/aws_mailer.py:70-83`

```python
def gen_subject_title() -> str:
    release = os.environ.get('RELEASE_VERSION', 'unknown')
    app_env = os.environ.get('APP_ENV', 'unknown')
    now = datetime.now()
    email_created = now.strftime("%Y%m%d_%H%M")
    city_name = "Ogre City Apartments for sale from ss.lv web_scraper_"
    email_subject = f"{city_name}{release}_{email_created} [{app_env}]"
    log.info(f"Email subject: {email_subject}")
    return email_subject
```

### CODE-3: Add environment label to the email body header
**File**: `src/ws/app/wsmodules/df_cleaner.py` — `create_email_body()`

Read `APP_ENV` and include it in the report header so it is visible in the body, not
only in the subject:
```python
app_env = os.environ.get('APP_ENV', 'unknown')
email_body_txt.append(f"=== Ogre Apartment Report — {today_str} [{app_env}] ===")
```

---

## Implementation priority

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| 1 | CI-1: Compute version in main.yml | ~15 lines YAML | High — fixes hardcoded version immediately |
| 2 | CODE-1: Uncomment env var in aws_mailer.py | 1 line | High — wires the existing plumbing |
| 3 | CODE-2: Add `[production]` / `[staging]` to subject | 3 lines | High — immediate env clarity |
| 4 | CI-2: Add `APP_ENV` to docker-compose.yml | 1 line | Required for CODE-2/3 to work |
| 5 | CI-3: Same version step in staging.yml | ~15 lines YAML | Medium — completes staging parity |
| 6 | CODE-3: Add env label to email body header | 2 lines | Low — redundant with subject label |

**Recommended merge order**: CI-2 → CODE-1 + CODE-2 (one PR) → CI-1 → CI-3
