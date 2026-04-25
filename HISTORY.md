# History

All notable changes to `codex-usage` are documented in this file.

## Unreleased

No unreleased changes yet.

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
