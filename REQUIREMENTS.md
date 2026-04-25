This application pulls Codex usage for OAuth accounts.

Requirements:

1. Implement in Python using `uv`.
2. Launchable as `codex-usage.py --param1 --param2 --etc`.
3. Match OpenClaw OAuth behavior for OpenAI Codex:
   - Build an OpenAI OAuth URL and have the user authenticate in browser.
   - User pastes redirect URL (or auth code) back into CLI.
   - Exchange at `https://auth.openai.com/oauth/token`.
   - If account exists, prompt for re-authentication.
4. `auth.json` stores all auth data needed to call Codex usage APIs.
5. `--show-usage` fetches usage for all known accounts.
