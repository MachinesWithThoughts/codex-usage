# codex-usage

`codex-usage` is a small CLI for collecting OpenAI Codex usage statistics across multiple stored accounts.

The current implementation stores account credentials in a local `auth.json` file, queries the OpenAI organization usage endpoints for each saved account, and prints a summary table showing current month usage.

## Current status

This is the initial application cut. It supports:

- adding or updating an account with `--add-account`
- displaying current month usage with `--display-usage`

## Important authentication note

The OpenAI organization usage endpoints used by this tool are administration endpoints.

At the time this version was built, the official OpenAI API docs showed these endpoints as requiring an **Admin API key**. An official OAuth flow for these usage endpoints was not identified in the current docs, so the first implementation uses an interactive credential capture flow instead of true OAuth.

That means:

- `--add-account` prompts for an account name, base API URL, and Admin API key
- credentials are stored locally in `auth.json`
- the tool verifies the account by making a live call to the organization costs endpoint

## Requirements

- `uv`
- Python 3.11 or newer
- Uses UV and launchable via command-line
- network access to the OpenAI API when adding accounts or displaying usage
- an OpenAI Admin API key for each organization/account you want to track

## Project layout

- `pyproject.toml` contains the project metadata
- `codex_usage/cli.py` contains the command-line interface
- `codex_usage/openai_usage.py` contains the OpenAI API calls and usage aggregation logic
- `codex_usage/storage.py` reads and writes `auth.json`
- `auth.json` is created locally after you add accounts

## Running with uv

From the project directory:

```bash
./codex_usage.py --help
```

This invocation does not require installing the package first and works cleanly in a restricted environment because it runs the module directly.

## Commands

### Show help

```bash
./codex-usage.py --help
```

### Add an account

```bash
./codex-usage.py --add-account
```

The command will prompt for:

- `Account name`: a friendly label used in reports
- `Base API URL`: default is `https://api.openai.com/v1`
- `Admin API key`: the OpenAI Admin API key used for organization usage endpoints

Example interactive flow:

```text
Account name: primary-org
Base API URL [https://api.openai.com/v1]:
Admin API key:
Stored account 'primary-org' in auth.json.
```

Behavior:

- if the account name is new, it is added to `auth.json`
- if the account name already exists, it is updated in place
- the tool verifies the credentials immediately
- if verification fails, the account is still saved and the error is recorded in `auth.json`

### Display usage

```bash
./codex-usage.py --display-usage
```

This command:

- loads all accounts from `auth.json`
- queries the OpenAI organization costs endpoint for the current month
- queries the OpenAI organization completions usage endpoint for the current month
- aggregates the results
- prints a table to the terminal

Example output shape:

```text
Account     | Month Cost | Requests | Input Tokens | Output Tokens | Cached Tokens | Last Verified            | Status
------------+------------+----------+--------------+---------------+---------------+--------------------------+--------
primary-org | USD 12.34  | 1,245    | 550,000      | 102,000       | 80,000        | 2026-04-24T22:10:00+00:00 | ok
```

If there are no configured accounts, the command prints:

```text
No accounts found. Use --add-account first.
```

## Data storage

### `auth.json`

Accounts are stored in a local `auth.json` file in the project directory.

Example structure:

```json
{
  "accounts": [
    {
      "name": "primary-org",
      "admin_api_key": "sk-admin-...",
      "base_url": "https://api.openai.com/v1",
      "created_at": "2026-04-24T22:00:00+00:00",
      "last_verified_at": "2026-04-24T22:05:00+00:00",
      "last_error": null
    }
  ]
}
```

Notes:

- `auth.json` is listed in `.gitignore`
- credentials are stored in plaintext locally in the current implementation
- treat this file as sensitive

## What the tool currently reports

For each account, the tool currently shows current-month totals for:

- cost from the organization costs endpoint
- request count from completions usage
- input tokens
- output tokens
- cached input tokens
- last verification timestamp
- current status

## Limitations

- the current implementation is based on Admin API keys, not OAuth
- it currently aggregates only the completions usage endpoint for token and request metrics
- it does not yet break usage down by model, project, or API key
- it does not yet export JSON or CSV reports
- it does not yet support encrypted local credential storage

## Troubleshooting

### Verification fails during `--add-account`

Possible causes:

- the key is not an Admin API key
- the base URL is wrong
- network access to the OpenAI API is blocked
- the organization does not allow the requested administration endpoint

If verification fails, the tool saves the account and records the most recent error in `auth.json`.

### `uv run` cannot access its default cache directory

In restricted environments, point `uv` at a writable cache directory:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m codex_usage.cli --help
```

### `--display-usage` shows an error status

The tool will keep the account in the table and show an error string in the `Status` column if the API call fails.

## Next improvements

Likely next steps for the application:

- replace local plaintext storage with encrypted credential storage
- add JSON and CSV export modes
- add model, project, and per-account breakdowns
- support configurable date windows
- revisit OAuth if OpenAI exposes a supported auth flow for these endpoints
