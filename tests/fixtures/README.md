# Test fixtures

Synthetic German speech for the tests that need real audio. The WAV files are not
in the repository (`*.wav` is git-ignored), so you generate them locally with the
three PowerShell scripts in this folder.

The scripts use the Windows text-to-speech engine (`System.Speech`). They run
offline and need no API key, but they only work on Windows with a German (`de-DE`)
voice installed. Every file is 16 kHz, 16-bit mono.

| Script | Creates | Content |
|---|---|---|
| `make_fixture.ps1` | `diktat_de.wav` | A plain German sentence (cleanup path) |
| `make_command_fixture.ps1` | `command_safeword.wav` | A sentence followed by a command with the safe word "Kimono" |
| `make_math_fixtures.ps1` | `math_quadratisch.wav`, `math_summe.wav`, `math_integral.wav`, `math_wurzel.wav`, `math_klammern.wav`, `math_prosodie.wav`, `math_delimiter.wav` | Spoken formulas |

```powershell
pwsh tests/fixtures/make_fixture.ps1
pwsh tests/fixtures/make_command_fixture.ps1
pwsh tests/fixtures/make_math_fixtures.ps1
```

## What uses them

- **`tests/test_stt_integration.py`** transcribes `diktat_de.wav` with a real
  faster-whisper model. It is skipped unless `FLEECH_STT_TEST=1` is set, and it
  downloads the model on its first run (`base` by default, override with
  `FLEECH_STT_TEST_MODEL`):

  ```powershell
  $env:FLEECH_STT_TEST = "1"
  .venv\Scripts\python -m pytest tests/test_stt_integration.py
  ```

- **The pipeline self-test** runs `diktat_de.wav`, `command_safeword.wav` and
  `math_quadratisch.wav` through the same pipeline the desktop app uses (speech
  recognition, mode routing, AI cleanup) and prints what would have been pasted.
  Missing files are skipped. It uses your own Fleech settings and the AI provider chosen there, so
  with a cloud provider the transcripts go to that provider.

  ```powershell
  .venv\Scripts\python -m fleech --pipeline-selftest tests/fixtures
  ```

  The installed app accepts the same flag: `Fleech.exe --pipeline-selftest <folder>`.

The other six `math_*` files are not used by any automated test. They are there for
trying out the formula recognition by hand.

Never put recordings of real dictation in this folder: it is meant for synthetic
speech only.
