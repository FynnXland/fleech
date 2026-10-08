# Security policy

## Supported versions

Only the [latest release](https://github.com/FynnXland/fleech/releases/latest) gets
security fixes. Installed copies find new releases by themselves, so a fix reaches
users with the next release. If you build from source, use the current `main` branch.

## Reporting a vulnerability

**Please don't open a public issue for security problems.** Report them privately via
GitHub: [**Report a vulnerability**](https://github.com/FynnXland/fleech/security/advisories/new)
(also on the repository's *Security* tab).

Helpful to include:

- the Fleech version and your operating system
- what an attacker can do, and under which conditions
- steps to reproduce, ideally a minimal proof of concept
- whether you'd like to be credited in the advisory

Please leave out real dictations, API keys and other personal data, even in a private
report.

Fleech is maintained by one person in their spare time, so responses are best effort.
You can expect an acknowledgement within 7 days. Once a fix is released, the advisory
is published and you are credited if you want to be.

## Scope

Fleech runs locally, hears everything you say into the microphone and types into
whichever window has focus. Reports about these areas are especially welcome:

- **Updates** ([`fleech/ui/updates.py`](fleech/ui/updates.py)): HTTPS only; downloads
  are only accepted from GitHub hosts, redirects included (a custom update feed is
  limited to its own host); the file size must match what the GitHub API reports, and
  if the release notes contain a `SHA256:` line (every release made with
  `packaging/release.py` does) or a custom feed has a `sha256` field, the checksum must
  match too, otherwise the file is deleted; the installer only runs when the user
  clicks.
  Anything that gets a different file installed, or skips one of these checks, is in
  scope.
- **API keys** for cloud providers ([`fleech/llm/apikeys.py`](fleech/llm/apikeys.py)):
  stored in the operating system's keychain (Windows Credential Manager, Secret Service
  on Linux), never in `settings.json` and never in the log. Environment variables and
  a `.env` file in the user folder are a fallback for setups without a keychain.
- **Text injection** ([`fleech/injection.py`](fleech/injection.py)): Fleech puts the text
  on the clipboard and simulates `Ctrl+V`. Text reaching the wrong window, or clipboard
  contents leaking, is in scope.
- **Prompt injection**: dictated text is wrapped in markers and passed to the language
  model as material, never as instructions. Dictation that makes Fleech do something other than clean up the
  text is in scope.
- **Local files** in `%APPDATA%\Fleech` (Linux: `~/.config/Fleech`): `settings.json`,
  `history.db`, `fleech.log`, and user overrides of `config.yaml` and the prompts.
- **The installer**: it installs per user, without administrator rights, into
  `%LOCALAPPDATA%\Programs\Fleech`.

## Out of scope

- The SmartScreen warning: the installer is not code-signed yet.
- Antivirus false positives on the PyInstaller build. Please report those to the
  antivirus vendor; an issue here is still welcome so others can find it.
- What a language model writes: hallucinations or poor cleanup are bugs, not
  vulnerabilities.
- Vulnerabilities in Ollama, Whisper/faster-whisper, Qt or a cloud provider itself.
  Please report them upstream. If Fleech uses one of them in an unsafe way, that is in
  scope.
- Attacks that require an attacker who already controls your user account.
