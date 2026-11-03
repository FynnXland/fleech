# Handoff from the Fleech chat: release 6.5.0

From the Fleech chat, 03.11.2026, for the slug `fleech`. Follows up on
`UEBERGABE-FYNNLAND.md` (27.10.2026, same folder), made to `LIEFERFORMAT.md`.
Folder: `E:\Entwicklung\07_Tools\Sprache-Audio\Fleech\docs\media\fynnland\`.

Fleech 6.5.0 is released on GitHub (`FynnXland/fleech`, release `v6.5.0`). What it brings,
in the words of the changelog: settings on six pages instead of ten, text snippets
(*Textbausteine*), translation per profile (*Übersetzen in*), and the window opens again
on the first click from the tray.

## New file

| File | What it is | Size |
|---|---|---|
| `media/einstellungen.webp` | 1600 × 1000. The settings window, page „KI & Text“: local Ollama as provider, the model, the intervention level. Real Qt window, rendered offscreen with invented data. | 39 KB |

Placement, visible content and caption are in `MEDIEN.md` (new last section, „Was ins Netz
geht, after paragraph 2“). All other media stay as they are: the pill, the bubble and the
profiles look the same in 6.5.0.

## Changes for the text

Checked against the code of 6.5.0.

| File | Now | Should be | Why |
|---|---|---|---|
| `page.md`, `## Lizenzen` | „Diese Beschreibung bezieht sich auf Version 6.4.0.“ | „Diese Beschreibung bezieht sich auf Version 6.5.0.“ | New release. |
| `page.md`, `## Profile`, after the paragraph | – | „Ein Profil kann den fertigen Text auch übersetzen, etwa ins Englische, Französische oder Spanische. Du diktierst weiter in deiner Sprache; geht bei der Übersetzung eine Zahl verloren, bleibt der Text unübersetzt.“ | New in 6.5.0: *Übersetzen in* per profile (`fleech/uebersetzung.py`). Fleech checks numbers, formulas, length and script and keeps the untranslated text if a check fails. |
| `page.md`, `## So läuft ein Diktat`, new last paragraph | – | „Was du immer gleich schreibst, etwa deine Signatur, legst du als Textbaustein an: Du sagst ein Kürzel, und genau dieser Text steht im Feld. Die KI fasst ihn nicht an.“ | New in 6.5.0 (`fleech/textbausteine.py`). A dictation that is only the code needs no AI at all. |
| `page.md`, FAQ „Welche Sprachen kann ich diktieren?“ | „Deutsch und Englisch.“ | „Deutsch und Englisch. Den fertigen Text kann ein Profil übersetzen: ins Englische, Französische, Spanische, Italienische, Niederländische, Portugiesische, Polnische oder Deutsche.“ | Same feature. Dictation itself stays German and English. |

No other sentence changes. The page names no settings pages, so the new layout needs no
text change. Installer size (about 1 GB), MIT, no account, local by default: unchanged.

**Not in 6.5.0:** rewriting selected text by voice and profiles as `SKILL.md` were planned
for 6.5.0 and move to 6.6.0. Nothing about them belongs on the page yet.

## How to make the picture again

From the Fleech project folder, with the Fleech environment:

```
.venv\Scripts\python docs\media\make_fynnland.py einstellungen
```

Same sandbox as the other parts: fresh temporary data folder, no real settings or history.
