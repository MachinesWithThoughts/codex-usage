# codex-usage Implementation Plan

## 1. Scope and Objectives

Build a Python CLI (managed with `uv`) that can:
- Add/re-authenticate OAuth accounts (`--add-account`)
- Persist all account auth data in `auth.json`
- Show usage for all stored accounts (`--show-usage`)

Implementation alignment:
- Mirror OpenClaw's OpenAI Codex OAuth + usage behavior and endpoint contracts.

## 2. Assumptions to Confirm Early

- OpenAI OAuth endpoints and usage endpoint remain stable:
  - `https://auth.openai.com/oauth/authorize`
  - `https://auth.openai.com/oauth/token`
  - `https://chatgpt.com/backend-api/wham/usage`
- Access token JWT includes enough identity data (`chatgpt_account_id`, profile email) to support account matching.
- `auth.json` format is not predefined, so we can define a stable schema.

If these assumptions are wrong, implementation details in Sections 5-6 should be adjusted first.

## 3. Project Setup (UV + Python)

1. Initialize project with `uv`:
   - `pyproject.toml`
   - dependency management and lockfile
2. Suggested runtime dependencies:
   - `httpx` for API calls
   - `pydantic` (or dataclasses) for schema validation
   - `rich` for readable usage output tables (optional but useful)
3. Suggested dev dependencies:
   - `pytest`
   - `pytest-mock` or `respx` for HTTP mocking
4. Create executable script:
   - `codex-usage.py` (required launch shape)
   - use `argparse` for flags (`--add-account`, `--show-usage`)

## 4. Proposed File/Module Layout

- `codex-usage.py` - CLI entrypoint
- `src/codex_usage/cli.py` - argument parsing + command dispatch
- `src/codex_usage/auth_flow.py` - login/exchange/re-auth logic
- `src/codex_usage/usage_api.py` - usage retrieval functions
- `src/codex_usage/store.py` - load/save/update `auth.json`
- `src/codex_usage/models.py` - account and auth models
- `tests/` - unit + integration-style CLI tests
- `auth.json` - local auth store (created on first account add)

## 5. Auth Storage Design (`auth.json`)

Use a schema that supports multiple accounts and future fields:

```json
{
  "version": 1,
  "accounts": [
    {
      "account_id": "string",
      "email": "string",
      "display_name": "string",
      "access_token": "string",
      "refresh_token": "string",
      "expires_at": "2026-04-24T22:00:00Z",
      "scopes": ["..."],
      "created_at": "2026-04-24T21:00:00Z",
      "updated_at": "2026-04-24T21:00:00Z"
    }
  ]
}
```

Implementation notes:
- Create file atomically (write temp + rename) to avoid corruption.
- Restrict file permissions where possible (`0600` on Unix).
- Validate on load; fail with clear remediation steps if malformed.

## 6. CLI Behavior

### `--add-account`

Flow:
1. Load `auth.json` (or initialize empty store).
2. Generate OpenClaw-style PKCE + `state`; construct authorize URL.
3. Print URL and instruct user to authenticate in browser.
4. Prompt user to paste final callback URL.
5. Parse callback URL or accept raw authorization code input.
6. Exchange at `https://auth.openai.com/oauth/token`.
7. Extract account identity from access-token JWT.
8. If account already exists:
   - Prompt to re-authenticate (replace token set) or cancel.
9. Persist updated account record in `auth.json`.
10. Print success summary.

Error handling:
- Invalid callback URL format
- OAuth exchange failure
- Network timeout/retryable API errors
- Store write failures

### `--show-usage`

Flow:
1. Load all accounts from `auth.json`.
2. For each account:
   - Refresh token with `grant_type=refresh_token` if expired/near expiry.
   - Request usage from `https://chatgpt.com/backend-api/wham/usage`.
3. Aggregate and print output (table + totals).
4. If one account fails, continue others and report partial failures.

Output recommendation:
- Columns: account/email, period, usage metric(s), last updated, status.

## 7. API Client Strategy

- OpenClaw-aligned constants:
  - OpenAI client ID: `app_EMoamEEZ73f0CkXaXp7hrann`
  - Redirect URI: `http://localhost:1455/auth/callback`
  - Usage headers include `User-Agent: CodexBar` and optional `ChatGPT-Account-Id`.
- Separate methods for:
  - `build_authorize_url()`
  - `exchange_authorization_code()`
  - `refresh_access_token()`
  - `fetch_usage()`

## 8. Validation and Tests

Minimum test coverage:
1. CLI parsing and mutually valid flag flows
2. Auth store read/write/upgrade behavior
3. Add account happy path
4. Re-auth existing account path
5. Show usage with:
   - multiple accounts
   - partial API failures
   - missing/invalid `auth.json`
6. Token refresh path (if implemented)

Command-level tests should assert exit codes and key output text.

## 9. Delivery Phases

1. Phase 1: Bootstrap + CLI skeleton + store layer
2. Phase 2: `--add-account` end-to-end flow
3. Phase 3: `--show-usage` end-to-end flow
4. Phase 4: error hardening + test suite
5. Phase 5: usage docs + examples

## 10. Definition of Done

- Running `codex-usage.py --add-account` can add or re-auth an account and persist to `auth.json`.
- Running `codex-usage.py --show-usage` returns usage for all known accounts and handles partial failures gracefully.
- `auth.json` schema is versioned and validated.
- Tests pass locally via `uv run pytest`.
