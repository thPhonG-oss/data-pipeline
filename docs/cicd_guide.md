# CI/CD Guide — Data Pipeline với GitHub Actions

> **Cập nhật:** 2026-03-28
> Tài liệu này hướng dẫn cấu hình và vận hành CI/CD pipeline tự động cho dự án.

---

## Tổng quan

```
Developer push code
        │
        ▼
GitHub Actions: CI (.github/workflows/ci.yml)
  ├── Lint (ruff) ──────────────► Fail fast nếu code style sai
  ├── Unit Tests (pytest) ───────► Kiểm tra logic không cần DB/Redis
  └── Docker Build Check ────────► Xác nhận Dockerfile không broken
        │
        │ (chỉ khi push vào main)
        ▼
GitHub Actions: Deploy (.github/workflows/deploy.yml)
  ├── SSH vào VPS
  ├── git pull origin main
  ├── docker compose build (pipeline, realtime-subscriber, realtime-processor)
  ├── docker compose up -d --no-deps (không restart DB/Redis)
  ├── python -m db.migrate (nếu có migration mới)
  └── Health check + Telegram notification
```

**Hai workflow:**

| Workflow | File | Trigger | Mục đích |
|---|---|---|---|
| **CI** | `ci.yml` | Mọi push, mọi PR | Lint + Test + Docker build check |
| **Deploy** | `deploy.yml` | Push vào `main` | SSH deploy lên VPS production |

---

## 1. Cấu hình GitHub Secrets

### 1.1 Vào Settings → Secrets

```
GitHub repo → Settings → Secrets and variables → Actions → New repository secret
```

### 1.2 Secrets bắt buộc cho Deploy

| Secret | Giá trị | Ghi chú |
|---|---|---|
| `VPS_HOST` | `123.456.78.90` | IP hoặc domain của VPS |
| `VPS_USER` | `ubuntu` hoặc `root` | User SSH trên VPS |
| `VPS_SSH_KEY` | Nội dung private key | Xem hướng dẫn bên dưới |
| `VPS_PORT` | `22` | SSH port (mặc định 22, có thể bỏ qua) |

### 1.3 Secrets tùy chọn (Telegram notifications)

| Secret | Giá trị |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token từ @BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID của bạn |

> Nếu không cài Telegram notification, xóa 2 step cuối trong `deploy.yml` (step "Notify on failure/success").

---

## 2. Tạo SSH Key cho GitHub Actions

### Bước 1 — Tạo key pair trên máy local

```bash
# Tạo ED25519 key (nhanh hơn RSA)
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_actions_deploy

# Sẽ tạo ra 2 file:
# ~/.ssh/github_actions_deploy      (private key — thêm vào GitHub Secrets)
# ~/.ssh/github_actions_deploy.pub  (public key — thêm vào VPS)
```

### Bước 2 — Thêm public key vào VPS

```bash
# Copy public key lên VPS
ssh-copy-id -i ~/.ssh/github_actions_deploy.pub <user>@<ip_vps>

# Hoặc thủ công:
cat ~/.ssh/github_actions_deploy.pub
# Paste vào file ~/.ssh/authorized_keys trên VPS
```

### Bước 3 — Thêm private key vào GitHub Secrets

```bash
# Copy toàn bộ nội dung private key
cat ~/.ssh/github_actions_deploy
```

Paste nội dung đó (bao gồm cả `-----BEGIN...` và `-----END...`) vào secret `VPS_SSH_KEY`.

### Bước 4 — Kiểm tra kết nối

```bash
ssh -i ~/.ssh/github_actions_deploy <user>@<ip_vps> "echo 'SSH OK'"
```

---

## 3. Cấu hình GitHub Environment (Production Gate)

`deploy.yml` sử dụng `environment: production`. Bạn có thể cấu hình **manual approval** — deploy chỉ chạy sau khi được approve:

```
GitHub repo → Settings → Environments → New environment
→ Đặt tên: production
→ Required reviewers: [chọn bản thân hoặc team]
→ Save protection rules
```

Khi có push vào `main`, workflow sẽ pause và gửi email/notification yêu cầu approve trước khi SSH vào VPS.

> Nếu không muốn manual gate, bỏ qua bước này — deploy sẽ tự động sau khi push vào `main`.

---

## 4. Branch Strategy

```
main ──────────────── Production (auto-deploy khi push)
  │
  └── develop ──────── Staging / Integration (chỉ chạy CI, không deploy)
        │
        ├── feature/xxx  ──── Feature branches (chỉ chạy CI)
        ├── fix/xxx      ──── Bug fix branches
        └── hotfix/xxx   ──── Hotfix branches (merge trực tiếp vào main)
```

**Quy trình phát triển:**
1. Tạo branch từ `develop`: `git checkout -b feature/my-feature develop`
2. Push code → CI chạy tự động
3. Tạo PR vào `develop` → CI chạy lại, review
4. Merge vào `develop` (không deploy)
5. Khi sẵn sàng release: merge `develop` → `main` → **auto-deploy lên production**

---

## 5. Chạy CI Locally (trước khi push)

### Cài test dependencies

```bash
pip install -r requirements-test.txt
```

### Chạy linter

```bash
# Check lint
ruff check .

# Check + auto-fix
ruff check . --fix

# Check formatting
ruff format --check .

# Auto-format
ruff format .
```

### Chạy tests

```bash
# Chạy toàn bộ test suite
pytest

# Chạy với coverage report
pytest --cov=etl --cov=realtime --cov-report=term-missing

# Chạy chỉ một nhóm tests
pytest tests/realtime/ -v
pytest tests/db/ -v

# Chạy nhanh (stop ngay khi có lỗi đầu tiên)
pytest -x
```

### Test report tham khảo

```
tests/db/test_timescale_migrations.py       15 tests   (SQL structure validation)
tests/realtime/test_auth.py                  4 tests   (DNSE auth + token cache)
tests/realtime/test_processor.py             6 tests   (OHLC transform + validate)
tests/realtime/test_session_guard.py         8 tests   (trading hours logic)
tests/realtime/test_watchlist.py             4 tests   (symbol list loading)
─────────────────────────────────────────────────────
TOTAL                                       37 tests
```

---

## 6. Workflow CI — Chi tiết

**File:** `.github/workflows/ci.yml`

### Job 1: `test` — Lint & Unit Tests

```
trigger: push vào bất kỳ branch | PR vào main/develop
runs-on: ubuntu-latest
python: 3.12
```

**Steps:**
1. `actions/checkout@v4` — clone repo
2. `actions/setup-python@v5` — cài Python 3.12 với pip cache
3. `pip install -r requirements-test.txt` — chỉ cài lightweight deps (không có vnstock)
4. `ruff check . --output-format=github` — lint, hiển thị lỗi theo format GitHub
5. `ruff format --check .` — check formatting
6. `pytest tests/ --cov=... --cov-report=xml` — chạy tests + coverage
7. Upload coverage lên Codecov (nếu có)

**Thời gian:** ~2–3 phút

### Job 2: `docker-build` — Build Check

```
trigger: PR vào main/develop | push vào main/develop
runs-on: ubuntu-latest
```

**Steps:**
1. `docker/setup-buildx-action@v3` — setup BuildKit
2. `docker/build-push-action@v5` — build image với `--no-push`
   - `VNSTOCK_API_KEY=` (trống) — test build không cần API key
   - GHA cache layer — lần đầu ~5 phút, sau đó ~1–2 phút

> **Lưu ý:** Job này chỉ chạy trên PRs và main/develop push để tiết kiệm GitHub Actions minutes. Feature branches chỉ chạy `test` job.

---

## 7. Workflow Deploy — Chi tiết

**File:** `.github/workflows/deploy.yml`

```
trigger: push vào main | workflow_dispatch (manual)
runs-on: ubuntu-latest
environment: production
concurrency: deploy-production (chỉ 1 deploy chạy cùng lúc)
```

### Steps trên VPS

```bash
# 1. git reset --hard origin/main
#    (không dùng git pull để tránh merge conflicts)

# 2. docker compose build --pull pipeline realtime-subscriber realtime-processor
#    --pull: luôn pull base image mới nhất

# 3. docker compose up -d --no-deps pipeline realtime-subscriber realtime-processor
#    --no-deps: giữ nguyên postgres và redis (dữ liệu không bị mất)

# 4. docker compose exec -T pipeline python -m db.migrate
#    -T: tắt pseudo-TTY (cần thiết trong CI context)

# 5. Health check: kiểm tra tất cả service đang "running"
#    Nếu fail → in logs + exit 1 (workflow fail, Telegram alert gửi)
```

### Manual Deploy (workflow_dispatch)

Vào tab **Actions** → **Deploy to VPS** → **Run workflow**:
- **run_migrations:** `true`/`false` — có chạy migration không
- **services:** danh sách services cần redeploy (mặc định tất cả 3)

Ví dụ deploy chỉ `realtime-processor` khi sửa processor code:
```
services: realtime-processor
run_migrations: false
```

---

## 8. Xử lý sự cố CI/CD

### 8.1 CI fail — Lint error

```bash
# Xem lỗi cụ thể
ruff check . --output-format=text

# Auto-fix những gì có thể
ruff check . --fix
ruff format .
```

### 8.2 CI fail — Test error

```bash
# Chạy test cụ thể đang fail
pytest tests/realtime/test_processor.py::test_transform_valid_message -v

# Xem full traceback
pytest --tb=long
```

### 8.3 Deploy fail — SSH connection refused

```bash
# Kiểm tra key đã được add vào VPS
ssh -i ~/.ssh/github_actions_deploy <user>@<vps_ip> "whoami"

# Kiểm tra authorized_keys trên VPS
cat ~/.ssh/authorized_keys
```

### 8.4 Deploy fail — docker compose up error

Workflow sẽ tự động in 50 dòng logs cuối của các services bị lỗi. Xem trong GitHub Actions run log.

Thường gặp:
- Migration lỗi syntax SQL → sửa file migration, push lại
- Container OOM → tăng RAM VPS hoặc giảm `MAX_WORKERS`

### 8.5 Rollback nhanh

**Cách 1 — Revert commit và push lại:**
```bash
git revert HEAD --no-edit
git push origin main
# Deploy tự động chạy với code đã revert
```

**Cách 2 — Manual deploy commit cũ:**
```bash
# Trên VPS
cd ~/apps/data-pipeline
git log --oneline -10
git reset --hard <commit_hash_cũ>
docker compose up -d --build pipeline realtime-subscriber realtime-processor
```

**Cách 3 — Dùng workflow_dispatch:**
1. Revert code trên GitHub (tạo revert commit)
2. Merge vào main → auto-deploy

---

## 9. Codecov Integration (tùy chọn)

Để xem coverage report trực quan trên GitHub:

1. Đăng ký tại [codecov.io](https://codecov.io) bằng GitHub account
2. Authorize repo
3. Thêm secret `CODECOV_TOKEN` (lấy từ codecov.io dashboard)
4. Cập nhật step upload trong `ci.yml`:
   ```yaml
   - uses: codecov/codecov-action@v4
     with:
       token: ${{ secrets.CODECOV_TOKEN }}
       files: coverage.xml
   ```

Badge cho README:
```markdown
[![codecov](https://codecov.io/gh/<owner>/data-pipeline/graph/badge.svg)](https://codecov.io/gh/<owner>/data-pipeline)
```

---

## 10. Tóm tắt secrets cần tạo

```
Repository → Settings → Secrets and variables → Actions
```

| Secret | Bắt buộc | Mô tả |
|---|---|---|
| `VPS_HOST` | ✅ | IP hoặc hostname VPS |
| `VPS_USER` | ✅ | SSH username (vd: `ubuntu`) |
| `VPS_SSH_KEY` | ✅ | Nội dung private key (ED25519) |
| `VPS_PORT` | ❌ | SSH port (mặc định 22) |
| `TELEGRAM_BOT_TOKEN` | ❌ | Deploy notifications |
| `TELEGRAM_CHAT_ID` | ❌ | Deploy notifications |
| `CODECOV_TOKEN` | ❌ | Coverage reporting |

---

*CI/CD guide cho Phase 7 — GitHub Actions deploy tự động lên VPS production. Cập nhật: 2026-03-28.*
