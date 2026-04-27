# History

All notable changes to `codex-usage` are documented in this file.

## Unreleased

No unreleased changes yet.

## 0.1.12 - 2026-04-26

### Added
- Added `--dump-json` for writing per-account/auth API snapshots to `./codex-usage-dump`.
- Added `--json` output mode for `--show-usage` that prints usage table data as JSON to `stdout`.
- Added coverage to ensure the text table hides the `Error` column when there are no error rows.

### Changed
- Renamed snapshot output directory from `./json` to `./codex-usage-dump`.
- In interactive `--tui` mode, `--json` is now ignored while `--dump-json` continues to write snapshots.
- Updated text table rendering to omit the `Error` column unless at least one account has an error.

## 0.1.11 - 2026-04-26

### Added
- `--help` output now includes the application version string.
- Added `--version` CLI flag for explicit version output.

### Changed
- Updated parser wiring so help/version information is sourced from package version metadata.

## 0.1.10 - 2026-04-26

### Added
- Added CA bundle resolution for HTTPS requests with precedence:
  1. `CODEX_USAGE_CA_BUNDLE`
  2. `SSL_CERT_FILE`
  3. `certifi` bundle fallback
- Added tests for SSL context CA bundle selection and validation behavior.

### Changed
- OAuth and usage HTTP requests now use the resolved SSL context consistently.

## 0.1.9 - 2026-04-26

### Added
- Added default CLI behavior so running with no parameters assumes `--show-usage`.
- Added test coverage for no-argument default mode routing.

### Changed
- Updated README command usage docs to describe no-parameter default behavior.

## 0.1.8 - 2026-04-26

### Added
- Added default auth store path fallback logic:
  - use `./auth.json` when present
  - otherwise use `~/.config/codex-usage/auth.json`
- Added tests for auth store path resolution order.

### Changed
- Updated CLI `--auth-file` help text to describe default lookup behavior.
- Updated README auth storage docs and examples to match the new default fallback location.

## 0.1.7 - 2026-04-25

### Added
- Added MIT license file (`LICENSE`) and package metadata license/classifier declarations.
- Added README screenshot references for `--show-usage` and `--tui` captures.

### Changed
- JSON snapshot files are now written with least-privileged permissions (`0600`).
- Clarified and normalized JSON snapshot filename conventions:
  - usage snapshots: `YYYYMMDD-HH24MMSS--account.json`
  - auth snapshots: `YYYYMMDD-HH24MMSS--account--auth.json`
- `--show-usage --json` no longer prints JSON payloads to `stdout`; snapshots are written to files.
- README updated with stronger warnings that JSON snapshots may include authorization codes, access tokens, refresh tokens, and account metadata.

## 0.1.6 - 2026-04-25

### Added
- When `--json` is enabled, per-account API snapshots are saved to `json/YYYYMMDD-HH24MMSS--account.json`.
- Added tests for JSON snapshot file creation and `--tui --json` argument support.
- Added authentication snapshot capture for `--add-account --json`, including OAuth exchange output and error/cancel traces.

### Changed
- Enabled `--json` in TUI mode; snapshot files are written on each completed TUI refresh cycle.
- Extended per-account refresh results to include raw usage/OAuth refresh payload sections for JSON snapshots.
- JSON snapshot output directory is `./json` (current working directory).

## 0.1.5 - 2026-04-25

### Added
- Added `HISTORY.md` with detailed version-to-version change tracking.
- Added regression coverage to ensure `--show-usage` uses threaded refresh retrieval.

### Changed
- Updated one-shot `--show-usage` to refresh accounts concurrently using threaded retrieval.
- Updated `README.md` to match current runtime behavior, including one-shot parallel refresh details.

## 0.1.4 - 2026-04-25

### Added
- `--tui` interactive mode for usage monitoring.
- `--debug` option to dump raw OAuth and usage API responses to `stderr`.
- Parallel account refresh in TUI mode, with incremental display updates as each account completes.
- TUI key bindings:
  - `SPACE` for immediate refresh.
  - `w` to toggle auto-refresh every 10 minutes.
  - `q` to quit.

### Changed
- `--tui` can be used directly (does not require `--show-usage`).
- Improved mode validation and CLI error messages for unsupported flag combinations.
- TUI and text output now show a single global `Last capture` time for the completed refresh cycle.

## 0.1.3 - 2026-04-24

### Changed
- Sorted console account output by:
  - available percentage descending (highest first),
  - time left ascending (shortest first),
  - account label ascending (tie-breaker).
- Updated tests to cover sorting behavior.

## 0.1.2 - 2026-04-24

### Changed
- Enhanced usage rendering to emphasize availability and reset timing for each usage window.
- Improved account usage row formatting in the text table.
- Expanded CLI test coverage for usage display behavior.

## 0.1.1 - 2026-04-24

### Added
- Structured tabular output for account usage.
- Initial CLI tests for account/usage output behavior.

### Changed
- Bumped package version metadata to `0.1.1`.

## v00.01.00 - 2026-04-24

### Added
- Initial `codex-usage` implementation and project scaffolding.
- OAuth PKCE login flow and callback parsing.
- Account store load/save/upsert logic with local `auth.json`.
- Usage fetching against `https://chatgpt.com/backend-api/wham/usage`.
- CLI entrypoint and baseline command structure.
- Unit tests for OAuth and account store modules.
