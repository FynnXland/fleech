# Media for fynnland.xyz/fleech/

All pictures show invented example data: the sentences are made up, the sender is
„Alex“, the address is `team@example.com`. The texts in the windows are real output
of Fleech's pipeline (version 6.4.x, local model `gemma3:4b-text`) for these invented
sentences, stored in `docs/media/examples.json`. No real dictation, no real user data.

The windows (notes, mail, AI chat) are neutral mock-ups drawn by the script, not
screenshots of real programs. The pill and its bubbles are Fleech's own Qt widgets,
rendered offscreen.

| Section (`page.md`) | After | File(s) |
|---|---|---|
| `Worum es geht` | 1 | `media/diktat.webm`, `media/diktat.mp4`, poster `media/diktat-poster.webp` |
| `So läuft ein Diktat` | 1 | grid: `media/vorher.webp`, `media/nachher.webp` |
| `Profile` | 1 | grid: `media/profil-standard.webp`, `media/profil-email.webp`, `media/profil-stichpunkte.webp`, `media/profil-ki-prompt.webp` |

## Worum es geht, after paragraph 1

**`media/diktat.webm` + `media/diktat.mp4`**, poster `media/diktat-poster.webp`
(1280 × 800, 7.0 s, seamless loop, no sound; WebM 116 KB, MP4 368 KB).

- Visible: A notes window titled „Notizen — team-update.txt“ with the heading
  „Wochen-Update“. Below it Fleech's pill: while recording it shows a moving waveform.
  After release a dark bubble above the pill shows the raw transcript with „ähm“ and
  „äh, nein“ and the line „Bereinige …“. Then the cleaned sentence appears in the
  window at once: „Hallo zusammen, ich schicke euch die Präsentation bis
  Freitagmittag, dann können wir sie am Montag durchgehen.“
- Caption: „Sprechen, loslassen: Der bereinigte Text steht im Feld.“

## So läuft ein Diktat, after paragraph 1

Grid of two stills (1600 × 1000 each).

**`media/vorher.webp`**
- Visible: The empty notes window. Below it the pill while it works; its bubble shows
  the raw transcript „Hallo zusammen, ähm, ich schicke euch die Präsentation bis
  Donnerstag, äh, nein, bis Freitagmittag, dann können wir sie am Montag
  durchgehen.“ and „Bereinige …“.
- Caption: „Vorher: der Rohtext mit „ähm“ und der zurückgenommenen Angabe.“

**`media/nachher.webp`**
- Visible: The notes window with the inserted text „Hallo zusammen, ich schicke euch
  die Präsentation bis Freitagmittag, dann können wir sie am Montag durchgehen.“ The
  pill is hidden again.
- Caption: „Nachher: Füllwörter und „Donnerstag, nein“ sind weg.“

## Profile, after paragraph 1

Grid of four stills (1600 × 1000 each). The same dictation („Also, ähm, die neue
Website soll nächste Woche online gehen, vorher müssen wir aber noch die Texte prüfen
und, äh, die Bilder komprimieren.“) in four profiles. Below each window the pill with
the profile's colour on its left ring and the profile name in a small capsule under it,
as Fleech shows it when the profile changes.

**`media/profil-standard.webp`**
- Visible: Notes window „Notizen — website.txt“ with the cleaned sentence; capsule
  „Standard“.
- Caption: „Standard: bereinigt, sonst wie gesagt.“

**`media/profil-email.webp`**
- Visible: Mail window „Neue Nachricht“, to `team@example.com`, subject
  „Website-Launch“, text with „Guten Tag,“, two sentences and „Viele Grüße, Alex“;
  capsule „E-Mail“.
- Caption: „E-Mail: Anrede, Absätze und Gruß.“

**`media/profil-stichpunkte.webp`**
- Visible: Notes window „Notizen — todo.md“ with three bullet points; capsule
  „Stichpunkte“.
- Caption: „Stichpunkte: das Wesentliche als Liste.“

**`media/profil-ki-prompt.webp`**
- Visible: AI chat window with a structured prompt (role, context, task, requirements)
  in the input field; capsule „KI-Prompt“.
- Caption: „KI-Prompt: als Auftrag für eine KI gegliedert.“
