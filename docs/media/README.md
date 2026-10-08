# README media

The GIFs and screenshots used in the project README. All of them come from
`make_media.py` in this folder. The script renders Fleech's own Qt widgets (the
pill, the main window, the settings) frame by frame at 2x resolution and turns them
into GIFs with ffmpeg. Nothing here is a screen recording.

| File | What it shows |
|---|---|
| `hero.en.gif`, `hero.de.gif` | Hold F9, speak, release: raw transcript in the bubble, cleaned text pasted at once |
| `profiles.gif` | One dictation run through four profiles: Standard, E-Mail, Stichpunkte, KI-Prompt (German only, because the format prompts write German) |
| `command.en.gif`, `command.de.gif` | Safe word "Kimono": a second recording rewrites the last sentence |
| `math.gif` | Spoken maths turned into LaTeX by the built-in parser. In the app this is opt-in (Settings → Ausgabe) |
| `tour.gif` | Main window: Home, Insights, Profile, Apps, Settings (KI) |
| `main-window.png`, `insights.png`, `profiles.png`, `settings-recording.png`, `settings-ai.png` | Static screenshots of the same pages |
| `pill.png`, `pill-states.en.png`, `pill-states.de.png` | The pill on its own, and a sheet of its states (card headings in English or German; the pill itself is German) |
| `social-preview.png` | GitHub social preview image (1280×640), uploaded by hand in the repository settings (*General → Social preview*). It lives here and not in `assets/`, because `assets/` is bundled into the app |

## The data is invented

- Every dictation, name, address and history entry is made up. The user is "Alex".
  The process names are generic (`notepad.exe`, `thunderbird.exe`, `code.exe`,
  `firefox.exe`, `obsidian.exe`, `winword.exe`).
- The window behind the pill is a neutral mock-up, not a real application. The F9
  keycap and the mouse pointer are demo elements, not part of Fleech.
- The texts Fleech produces are real output. `examples.json` stores what was
  "spoken" and what Fleech's pipeline made of it with the local model gemma3:4b
  (Ollama, temperature 0). Only speech recognition is replaced by a stand-in that
  returns the scripted sentence.
- The app's interface is German, so the pill and the windows show German labels in
  the English GIFs as well.
- GIF time is compressed. In the app, the cleanup takes about half a second to a
  second; the GIFs hold each step long enough to read it.

## Regenerating

Run these from the repository root with Fleech's Python environment. ffmpeg has to
be on the `PATH`, or set the `FFMPEG` environment variable.

```
python docs/media/make_media.py                # all scenes, from examples.json
python docs/media/make_media.py hero tour      # selected scenes only
python docs/media/make_media.py --beispiele    # re-run the pipeline, rewrite examples.json
python docs/media/make_media.py --liste        # list the scenes
```

`--beispiele` needs a running Ollama with `gemma3:4b`. Run it only when you want new
texts, then check the diff of `examples.json`. A different model or Ollama version
can change the wording.

The script never touches your own Fleech data. Before it imports Fleech it points
`APPDATA`/`LOCALAPPDATA` (or `XDG_*` on Linux) at a temporary folder and stops if
Fleech's data folder is not inside it. The list of running programs, the foreground
window and the credential store are replaced by fixed stand-ins, and no window is
shown on screen.
