# Handoff from the Fleech chat: pictures for fynnland.xyz

From the Fleech chat, 27.10.2026, for the slug `fleech`. Answers
`08_Auftritt/fynnland/docs/uebergaben/fleech.md`, made to `LIEFERFORMAT.md`.
Folder: `E:\Entwicklung\07_Tools\Sprache-Audio\Fleech\docs\media\fynnland\`.

## What is in the folder

| File | What it is | Size |
|---|---|---|
| `tile.svg` | Fleech's mark: the white five-bar waveform from the app icon (`assets/logo.svg`), on transparent, no text. Cropped tighter than the icon so it reads at 62 % of an 80 px tile. | 0.6 KB |
| `background.webp` | 1920 × 1200. A calm notes window with an invented German sentence, below it Fleech's pill while it listens (moving waveform). Everything important sits in the middle; top and bottom stay empty for the launcher's darkening. | 41 KB |
| `media/diktat.webm`, `media/diktat.mp4`, `media/diktat-poster.webp` | 1280 × 800, 7.0 s, seamless loop, no sound: record, raw transcript in the bubble, the cleaned text appears in the field. Poster = first frame. | 116 KB / 368 KB / 32 KB |
| `media/vorher.webp`, `media/nachher.webp` | 1600 × 1000. Raw transcript with „ähm“ while Fleech cleans up, then the inserted text. | 27 / 29 KB |
| `media/profil-standard.webp`, `-email`, `-stichpunkte`, `-ki-prompt` | 1600 × 1000. The same dictation in four profiles, the pill shows the profile colour and name. | 22 to 54 KB |
| `MEDIEN.md` | Where each medium goes in `page.md`, what is visible (for `alt`), German caption. | |

**Colours**

- `tileColor`: **`#256AB0`**, the blue end of the app icon's gradient (`#35C0D8` → `#256AB0`).
  White on it: contrast 5.6 : 1.
- `accentColor`: **`#35C0D8`**, Fleech's accent colour in the app (`fleech/ui/theme.py`).

**Not delivered, on purpose**

- **No settings screenshot.** The settings window is being rebuilt for 6.5.0 (ten pages
  become six). A shot of the current code would show something no released version has;
  a shot of 6.4 would be outdated with the next release. It comes with the 6.5.0 release.
- No moving background, no music. Both optional; say if you want a moving background, the
  script can render one from the same scene.

**Rules kept:** no real dictations (the test set `Documents\Fleech-Pruefsatz` was not
touched), only invented sentences; name „Alex“, address `team@example.com`; no user name in
any path or title; no mouse pointer, no added text, arrows, keycaps or labels (all text in
the pictures is either the invented document or Fleech's own pill and bubble); no
third-party logos. The windows around the pill are neutral mock-ups, not real programs.
Whisper and Gemma appear nowhere in the pictures.

## Corrections for the text

Checked against the code of the published version (6.4.0/6.4.1).

| File | Now | Should be | Why |
|---|---|---|---|
| `app.json`, `about` | „Acht Profile lassen sich einzelnen Programmen zuordnen.“ | „Acht Profile sind dabei, eigene kommen dazu. Jedes lässt sich einzelnen Programmen zuordnen.“ | Eight are presets (`_default_profiles`), the profile page has „Hinzufügen“. There is no limit of eight. |
| `page.md`, `## Profile` | „Fleech kennt acht Profile.“ | „Fleech bringt acht Profile mit, weitere legst du selbst an.“ | Same as above. |
| `page.md`, `## So läuft ein Diktat`, paragraph 3 | „Mit Strg+Alt+Z fügst du den Rohtext auch jederzeit absichtlich ein.“ | „Mit Strg+Alt+Z ersetzt du den zuletzt eingefügten Text durch den Rohtext, bis zu zwei Minuten lang und solange der Cursor noch dahinter steht.“ | Strg+Alt+Z replaces the last insertion, not „jederzeit“: limit 120 s, and only if the cursor is still behind that text (`nachbereitung.py`, `_UNDO_MAX_AGE_S`). |
| `page.md`, `## Was ins Netz geht` | „Das Protokoll in Fleech zeigt nur Wortzahlen, keine Inhalte.“ | „Das Protokoll in Fleech zeigt standardmäßig nur Wortzahlen, keine Inhalte.“ | For troubleshooting the user can switch dictation text into the log (settings, „Diktattexte ins Protokoll“). Off by default. |
| `page.md`, `## Was ins Netz geht` | „Beim Einrichten lädt Fleech Spracherkennung und KI-Modell herunter.“ | „Beim Einrichten lädt Fleech Spracherkennung und KI-Modell herunter und installiert, falls nötig, Ollama.“ | Optional precision: the setup installs Ollama via winget if it is missing. |

All other facts checked and correct: F9 as default key, raw text on too strong deviation,
three operating modes, model check on by default, cloud provider sends text, never audio,
installer about 1 GB (1.02 GB), unsigned, no admin rights, Linux only from source, German
and English, MIT.

**Gemma terms (open point from your handoff):** done. `THIRD-PARTY-NOTICES.md` in the
Fleech repository now has a „Models“ section: Whisper large-v3-turbo (MIT), the optional
German Whisper model (Apache-2.0), Gemma 3 with the Gemma Terms of Use and Prohibited Use
Policy including the required notice sentence, and Ollama (MIT). It is committed locally and
becomes public with the next push to `main`; tell Fynn if the page should not go live
before that.

## When 6.5.0 is released

6.5.0 is not released yet (status 27.10.: parts 1 and 2 of four done). What changes for the
text, as far as decided now:

- `page.md`, `## Lizenzen`: „Diese Beschreibung bezieht sich auf Version 6.4.0.“ → 6.5.0.
- New: **Übersetzen je Profil.** A profile can translate the finished text into English,
  French, Spanish, Italian, Dutch, Portuguese, Polish or German; you keep dictating in your
  language. Fits under `## Profile`, and the FAQ „Welche Sprachen kann ich diktieren?“
  could add: „Den fertigen Text kann ein Profil in eine andere Sprache übersetzen.“
- New: **Textbausteine.** A spoken shortcut inserts fixed text (for example a signature),
  untouched by the AI.
- Settings on six pages instead of ten. The text names no settings pages, so no sentence
  changes; the settings screenshot follows then.
- Still open in 6.5.0 (rewrite selected text by voice, profiles as SKILL.md): I will list
  them in the release handoff.

## How to make the pictures again

From the Fleech project folder, with the Fleech environment:

```
.venv\Scripts\python docs\media\make_fynnland.py            # everything
.venv\Scripts\python docs\media\make_fynnland.py diktat     # only one part
```

Parts: `kachel`, `hintergrund`, `diktat`, `vorher-nachher`, `profile`. Needs ffmpeg (PATH or
`FFMPEG`). No server and no port: the script renders Fleech's real Qt widgets offscreen in
a fresh temporary data folder (the sandbox from `docs/media/make_media.py`) and never reads
real settings, history or logs. The texts come from `docs/media/examples.json` (real
pipeline output for invented sentences; `make_media.py --beispiele` makes it again).
