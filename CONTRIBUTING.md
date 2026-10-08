# Contributing to Fleech

Thanks for your interest in Fleech. Bug reports, ideas and pull requests are all
welcome, in English or German (*Deutsch ist genauso willkommen*).

Fleech is maintained by one person. For anything bigger than a small fix, please open
an issue first so we can agree on the approach before you spend time on it.

- **Bugs and ideas:** use the [issue forms](https://github.com/FynnXland/fleech/issues/new/choose).
  The log contains your dictated text, so redact it before pasting.
- **Security problems:** report them privately, see [SECURITY.md](SECURITY.md).
- **How the code is organised:** [docs/architecture.md](docs/architecture.md).

## Development setup

### Windows

Requires Python 3.11.

```powershell
git clone https://github.com/FynnXland/fleech.git
cd fleech
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m fleech          # starts the desktop app (pythonw: without a console)
```

`requirements-dev.txt` installs the runtime dependencies from `requirements.txt` plus
pytest, Pillow and PyInstaller. The `nvidia-*` packages in `requirements.txt` (over
1 GB) are only needed for speech recognition on an NVIDIA GPU; without them Fleech
falls back to the CPU.

Fleech runs as a single instance and uses the same user folder (`%APPDATA%\Fleech`)
whether it is installed or started from source. Quit an installed Fleech first
(tray icon → *Beenden*), otherwise the second start only brings up the first one's
window.

### Linux (X11)

```bash
bash packaging/setup-linux.sh       # creates the venv in ~/.venvs/fleech
~/.venvs/fleech/bin/python -m fleech
```

- The venv lives outside the project (override with `FLEECH_VENV`), so the checkout can
  sit on an NTFS drive shared with Windows.
- The script installs `pynput` separately with `--no-deps`: its `evdev` dependency is
  only needed for the Wayland/uinput backend, has no binary wheels and fails to build
  without the Python headers. The X11 backend only needs `python-xlib`.
- If `sounddevice` can't find PortAudio, install your distribution's `libportaudio2`.
- X11 is the supported session. Under Wayland, several features that rely on X11 are
  limited (`WAYLAND_LIMITS` in `fleech/platformpaths.py`); Fleech lists them under
  *Einstellungen → Advanced* instead of failing silently.

### Ollama is optional

The tests mock the language model, so you don't need Ollama to work on Fleech. To try
the AI cleanup in the running app, install [Ollama](https://ollama.com) and
`ollama pull gemma3:4b`, or pick a cloud provider or "Ohne KI" (no AI) under
*Einstellungen → KI*.

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```

- About 1,600 tests, under a minute. Speech recognition and the LLM are mocked, Qt runs
  offscreen, and `tests/conftest.py` redirects settings, history and the keychain to
  temporary stand-ins.
- **Every new behaviour needs a test.** A bug fix comes with a test that fails without
  the fix.
- Real speech recognition is opt-in: generate the audio fixtures and set
  `FLEECH_STT_TEST=1`, see [tests/fixtures/README.md](tests/fixtures/README.md).
- GitHub Actions runs the suite on Windows for every pull request and every push to
  `main` ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)).

**Prompt and LLM changes must be checked live.** Unit tests mock the model, so they
say nothing about how a prompt behaves. Run a few representative sample dictations
through the real `ChatClient` (`fleech/llm/client.py`) against a local Ollama, or use
`python -m fleech --pipeline-selftest tests/fixtures`, and write in the pull request
which model you used and what you compared.

## Code conventions

- **Naming:** domain terms are German (`freihand`, `profil`, `nachbereitung`,
  `kontext`), technical infrastructure is English (`pipeline`, `injection`, `history`,
  `StateBus`). The app's concepts have no natural English equivalent, so the mix is
  deliberate. Code comments and docstrings are German. UI texts are German too; write
  them with proper umlauts (ä, ö, ü, ß), never `ae`/`oe`/`ue`.
- **Put new code where it belongs, not where there is room.** That is how
  `main_window.py` once grew to almost 3,000 lines. `tests/test_ui_struktur.py` and `tests/test_kernstruktur.py`
  enforce line limits per file, a maximum function length, and the direction of
  imports (for example, `usersettings` imports `profiles` but never the other way
  round, the core never imports the UI, and a part never imports its whole). **If a
  limit trips, never raise the number.** Give the new topic its own module.
- **Platform-specific code stays behind the existing seams:** `platformpaths`,
  `clipboard`, `audiofocus`, `ui/x11tools`, `ui/autostart`, `singleinstance`. No
  scattered `sys.platform` checks.
- **Qt pitfalls** that caused real crashes (lambdas capturing a Qt parent, rendering
  screenshots offscreen, scoping style sheets) are collected in [CLAUDE.md](CLAUDE.md)
  under "Qt-/Windows-Fallen".
- **New dependencies:** runtime packages go into `requirements.txt`, tools into
  `requirements-dev.txt`. Add every new runtime dependency to
  [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Its license must not restrict
  Fleech's MIT license: permissive licenses are fine, LGPL only as a separately loaded
  library, no GPL.
- **UI changes:** attach a before/after screenshot to the pull request, made with sample
  data.

## Privacy

Everything committed is public forever, including the history of a branch you later
delete. Never commit real dictations, log files, `settings.json`, `history.db`, API
keys, user names or local paths, not in code, tests, fixtures, screenshots or commit
messages. Test data is made up. `tests/test_keine_geheimnisse.py` scans tracked files
for common key formats, but it only catches the worst cases.

## Versions and changelog

The maintainer bumps `fleech/version.py` and writes the [CHANGELOG](CHANGELOG.md) entry;
`tests/test_changelog.py` checks that every version has one. Please don't change either
in a pull request. Instead, describe in the pull request what changes for someone who
*uses* Fleech. That text becomes the changelog entry.

## Building

```powershell
.venv\Scripts\python packaging\build.py               # → dist\Fleech\Fleech.exe
.venv\Scripts\python packaging\build.py --gpu         # bundles the CUDA libraries (remembered; --cpu switches back)
.venv\Scripts\python packaging\build.py --installer   # also → dist\FleechSetup-<version>.exe
```

The installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`). On Linux, `packaging/build.py` builds
`dist/linux/Fleech/Fleech`, and `--install` copies it to `~/.local/opt/Fleech` with a
menu entry. Releases are published by the maintainer with `packaging/release.py`.

## AI coding agents

[CLAUDE.md](CLAUDE.md) contains the instructions the maintainer gives AI coding agents
(in German). Its conventions match this guide. Some parts describe the maintainer's own
machine, such as syncing the build into the local installation; if you work with an
agent, make sure it doesn't overwrite your own installed Fleech.

## License

Fleech is licensed under the [MIT License](LICENSE). Unless you explicitly state
otherwise, any contribution you submit for inclusion in Fleech is licensed under the
MIT License as well, without additional terms or conditions.
