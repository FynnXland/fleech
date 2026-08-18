# Prompt für eine orchestrierte Tiefenanalyse

Für eine KI, die **Zugriff auf den Projektordner hat** und **eigene Unteragenten
starten kann** (Claude Code mit Agent-Werkzeug, ein Workflow-Lauf, ein
vergleichbares Gespann). Sie untersucht das System auf mehreren Bahnen parallel
und liefert am Ende **einen Bericht** — sie setzt nichts um.

Der Unterschied zu `deep-research-prompt.md`: Dort begutachtet ein Außenstehender
zwei angehängte Dateien. Hier läuft die Untersuchung **im Projekt**, mit Tests,
Protokollen und echten Daten — und sie fragt nicht nur „was ist kaputt", sondern
vor allem „was fehlt".

Kopieren, absenden, fertig. Der Prompt nennt die Randbedingungen selbst.

---

## So startest du es in Claude Code

Kurz zur Mechanik, weil sie eine verbreitete Fehlvorstellung betrifft:
**Unteragenten sind keine neuen Sitzungen.** Sie laufen in der Sitzung, die du
gerade offen hast — eigenes, frisches Kontextfenster, eigener Modell-Aufruf, aber
kein eigener Chat und keine Historie. Jeder bekommt genau den Prompt, den der
Orchestrator ihm schreibt, arbeitet, und gibt **einen Text** zurück. Mehr sieht
der Orchestrator von ihm nicht.

Zwei Werkzeuge stehen dafür bereit, und der Unterschied entscheidet die Frage
nach der Denktiefe:

| | `Agent` | `Workflow` |
|---|---|---|
| Umfang | ein Unteragent je Aufruf | ein Skript, das alle steuert |
| Modell je Agent | ja (`model`) | ja (`opts.model`) |
| **Denktiefe je Agent** | **nein** — erbt von der Sitzung | **ja** (`opts.effort`) |
| Ablauf | mehrere Aufrufe in EINER Nachricht laufen parallel | `parallel()`, `pipeline()`, Phasen, Schleifen |

Für diesen Auftrag also **`Workflow`**: Fable 5 als Orchestrator, jeder
Unteragent ausdrücklich auf Opus 5, Denktiefe je Bahn geregelt. Das steht so im
Prompt.

**Der Haken:** `Workflow` läuft nicht von selbst an. Es braucht eine ausdrückliche
Freigabe — das Schlüsselwort `ultracode`, oder du sagst in eigenen Worten „nutze
einen Workflow". Ohne das bekommst du eine Rückfrage statt eines Laufs. Das ist
eine Kostenbremse: So ein Lauf startet ein Dutzend Agenten. Der Prompt enthält
die Freigabe bereits im Abschnitt WIE DU ORCHESTRIERST — schreib zur Sicherheit
trotzdem `ultracode` dazu.

Zur Größe: gleichzeitig laufen höchstens `min(16, CPU-Kerne − 2)` Agenten, der
Rest wartet. Zwölf bis dreizehn sind ein normaler Lauf. Den Fortschritt siehst du
in einer interaktiven Sitzung mit `/workflows`.

---

## Der Prompt

```text
Du bist der Orchestrator einer Tiefenanalyse von Fleech. Du hast Zugriff auf den
Projektordner und kannst Unteragenten starten. Du setzt in diesem Auftrag NICHTS
um: kein Umbau, kein Commit, kein Build, keine Versionsänderung. Am Ende steht ein
Bericht, und dann fragst du, womit ich anfangen will.

═══════════════════════════════════════════════════════════════════════
WAS FLEECH IST
═══════════════════════════════════════════════════════════════════════

Eine vollständig lokal laufende deutsche Diktier-Anwendung für Windows 11
(Linux nachrangig): Python 3.11, PySide6, faster-whisper auf der GPU, Ollama mit
gemma3:4b. Sie läuft im Tray. Der Weg ist immer derselbe — Mikrofon → Erkennung
→ Modus-Erkennung → Sprachmodell-Bereinigung → Qualitäts-Guards → der fertige
Text landet über die Zwischenablage im gerade fokussierten Eingabefeld. Kein
Cloud-Dienst, keine Netzverbindung im Betrieb.

Verbindliche Einstiegspunkte, in dieser Reihenfolge zu lesen:

  CLAUDE.md                       Arbeitsregeln, Modulkarte, die real
                                  aufgetretenen Qt-/Windows-Fallen
  docs/fleech-gesamtkonzept.md    ~2300 Zeilen: jede Funktion, jede Einstellung,
                                  die Messwerte und die Begründungen dahinter
  CHANGELOG.md                    was sich wann für den Benutzer geändert hat
  %APPDATA%\Fleech\fleech.log     der echte Betrieb, kein Testlabor

Größenordnung: 101 Module / rund 24.000 Zeilen Anwendungscode, 71 Testdateien /
1.224 Tests, Version 5.10.1.

WICHTIG, damit du keine Zeit verlierst: Der Freihand-Modus (Dauerlauschen auf ein
Startwort) ist ab 5.10.1 absichtlich stillgelegt — `freihand.STILLGELEGT = True`.
Der Code ist vollständig da, er wird nur nicht mehr gestartet. Das ist kein
Befund. Ob und wie man das Problem dahinter (Startworterkennung im Dauerbetrieb
zu ungenau) lösen sollte, ist dagegen eine sehr willkommene Frage.

═══════════════════════════════════════════════════════════════════════
ZIELGRUPPE — an ihr misst sich jeder Vorschlag
═══════════════════════════════════════════════════════════════════════

Windows-Desktop, ein Rechner, ein Mensch, den ganzen Tag.

  Kern heute:    Leute, die mit KI arbeiten. Sie diktieren Prompts in Claude
                 Code, ChatGPT, eine IDE — lange, strukturierte, präzise Texte,
                 bei denen jedes falsch eingefügte Wort teuer ist.
  Ebenso real:   der ganz normale Tag. Chats, E-Mails, Notizen, Messenger,
                 Suchfelder. Kurze Diktate, ständiger Fensterwechsel.
  Nachrangig:    Linux/X11 läuft, ist aber nicht der Alltag des Benutzers.

Beides muss dieselbe Anwendung bedienen. Ein Vorschlag, der den einen Fall
verbessert und den anderen verschlechtert, muss das ausdrücklich sagen.

═══════════════════════════════════════════════════════════════════════
DIE BAHNEN — je ein Unteragent, eigener Auftrag, eigener Beleg
═══════════════════════════════════════════════════════════════════════

Setze die Bahnen A–I an — je ein Unteragent, in Wellen, wie weiter unten unter
WIE DU ORCHESTRIERST beschrieben. Grundregel dabei: Kein Unteragent bekommt die
VORSCHLÄGE eines anderen zu sehen. Sonst schreiben sie voneinander ab und du
bekommst neunmal dieselbe Beobachtung in neun Formulierungen. Belegte Tatsachen
gibst du weiter, Meinungen nicht. Zusammengeführt wird am Ende von dir; Bahnen
dürfen sich überschneiden, doppelte Befunde fasst du zusammen und nennst die
Bahn, die ihn am besten belegt hat.

── A · Anspruch gegen Wirklichkeit ───────────────────────────────────
Nimm jede Zusage, die Fleech dem Benutzer macht — in `docs/fleech-gesamtkonzept.md`,
in den Hilfetexten und Tooltips der Einstellungen, im Onboarding, in
`docs/FUER-EMPFAENGER.md` — und halte sie gegen den Code. Welche Zusage hält er
nicht, hält er nur unter Bedingungen, oder hält er nur, solange nichts schiefgeht?
Interessiert mich besonders dort, wo der Text eine Garantie klingen lässt und der
Code eine Heuristik ist.

── B · Der Aufnahmeweg, Schritt für Schritt ──────────────────────────
Von der gedrückten Taste bis zum eingefügten Text, jeder Zwischenschritt einzeln.
Die drei Auslöse-Arten (halten / umschalten / anstupsen), Pause, Abbrechen,
Fertig, Fokus-Rückgabe, Zwischenablage, Injection. Frage bei jedem Schritt: Wo
kann er hängen, doppelt feuern, in falscher Reihenfolge kommen, oder Text
verlieren? Was passiert, wenn der Benutzer währenddessen das Fenster wechselt,
den Rechner sperrt, das Mikrofon abzieht, ein zweites Mal auslöst?
Lies dafür das echte Protokoll (`fleech.log`), nicht nur den Code — dort steht,
was tatsächlich passiert ist, samt Zeitstempeln.

── C · Der Textweg und seine Wächter ─────────────────────────────────
STT → Routing → Sprachmodell → `fleech/textfilter.py` → Injection. Was überlebt,
was wird still verworfen? Die Guards greifen bewusst hart (erfundene Ergänzungen,
Wortsalat, fremde Schrift, Sinnumkehr) — konstruiere Eingaben, bei denen sie das
Falsche tun: einen korrekten Text abfangen oder einen kaputten durchlassen. Und
die zweite, wichtigere Frage: Erfährt der Benutzer überhaupt, dass ein Wächter
eingegriffen hat, und kann er etwas dagegen tun?

── D · Zustand, Threads, Zeitannahmen ────────────────────────────────
Vier Threads teilen sich Zustand: Qt-Oberfläche, PortAudio-Callback,
Prüf-Threads, Verarbeitungs-Worker. Wo wird geteilter Zustand ungesichert
angefasst, wo hängt Korrektheit an einer Zeitannahme, die unter Last nicht gilt?
Hinweis: Genau dieses Feld hat ein externes Gutachten zu 5.10.0 schon beackert.
Wiederhole es nicht — lies nach, was dort stand, und suche das, was dort NICHT
stand. Zwei der sechs damaligen Befunde hielten der Nachprüfung übrigens nicht
stand; beide klangen plausibel und waren am Code widerlegbar. Prüfe deine eigenen
Befunde, bevor du sie aufschreibst.

── E · Bedienung ohne Handbuch ───────────────────────────────────────
Vom ersten Start bis zum eingespielten Alltag. Onboarding, elf
Einstellungsseiten, vier Hauptfenster-Seiten, Tray, die Pille am Bildschirmrand.
Welche Einstellung findet nie jemand? Welche versteht man erst, nachdem man sie
falsch gesetzt hat? Welche ist gefährlich, ohne es zu sagen? Und wo muss der
Benutzer etwas wissen, das nirgends steht? Rendere die Seiten offscreen und sieh
sie dir an (CLAUDE.md erklärt, wie) — beurteile keine Oberfläche nur aus dem
Quelltext.

── F · Insights ──────────────────────────────────────────────────────
Die Seite ist heute ein Kachelraster. Das ist ordentlich und tot. Zwei Fragen,
in dieser Reihenfolge:
  1. Was will ein Mensch über sein eigenes Diktieren eigentlich wissen — und was
     davon ist bloß Eitelkeit, die nach drei Tagen niemanden mehr interessiert?
  2. Was davon lässt sich aus `history.db` heute schon beantworten, und was
     bräuchte neue Erfassung? Sag es bei jedem Vorschlag ausdrücklich dazu.
Danach: Vorschläge für eine Seite, die man anfassen mag — interaktiv, gern auch
spielerisch, aber ohne Zahlen, die schmeicheln statt zu stimmen. Beschreibe jeden
Vorschlag so konkret, dass man ihn bauen könnte: welche Daten, welche Interaktion,
was passiert beim Klick.

── G · Profile und App-Zuordnung ─────────────────────────────────────
Das ist inzwischen eine der wichtigsten Fähigkeiten: Fleech erkennt die Ziel-App
(Prozessname + optional Fenstertitel) und schaltet Profil, Modus, Sprache und
Prompt um. Prüfe den Mechanismus (`fleech/profiles.py`, `ui/desktopapp/profil.py`,
`ui/pages/profiles.py`, `ui/pages/apps.py`): Wo greift er daneben, wo ist die
Reihenfolge der Regeln überraschend, wo merkt der Benutzer nicht, welches Profil
gerade gilt? Dann die Erweiterungsfrage: Was fehlt, damit das Feature seine Rolle
wirklich trägt? Denke an Zuordnungsvorschläge aus dem eigenen Verlauf, an
Profile, die man weitergeben kann, an Regeln jenseits von Prozess und Titel, an
app-eigene Wörterbücher. Bewerte jede Idee auch dagegen, ob sie die Sache
kompliziert macht.

── H · Funktionserweiterungen ────────────────────────────────────────
Die Hauptbahn. Nicht Vorschläge, die mir gefallen — Vorschläge, die sinnvoll
sind. Der Unterschied: Ein sinnvoller Vorschlag lässt sich an einem Problem
festmachen, das im Code, im Protokoll oder im Verlauf nachweisbar existiert oder
sich zwingend aus der Zielgruppe ergibt.
Decke dabei beide Nutzungsarten ab (KI-Arbeit und Alltag) und sieh dir an, was
vergleichbare Anwendungen können, ohne daraus eine Wunschliste zu machen.
Jeder Vorschlag in genau dieser Form:

    Was            in einem Satz, aus Sicht des Benutzers
    Für wen        welche der beiden Nutzungsarten, und wie oft im Tag
    Das Problem    woran man es festmacht — Datei, Protokollzeile, Messwert
    Wie            der kürzeste Weg dorthin, mit den betroffenen Modulen
    Aufwand        klein (Stunden) / mittel (Tag) / groß (mehrere Tage)
    Risiko         was dabei kaputtgehen kann, was es komplizierter macht
    Ohne das       was passiert, wenn man es einfach lässt

Sortiere am Ende nach Verhältnis von Nutzen zu Aufwand, nicht nach Begeisterung.

── I · Der Gegenspieler ──────────────────────────────────────────────
Ein Unteragent, der zum Schluss läuft und gegen alles antritt, was die anderen
vorgeschlagen haben. Sein Auftrag: Welcher Vorschlag löst ein Problem, das der
Benutzer gar nicht hat? Welcher macht die Anwendung schwerer bedienbar, als er
Nutzen bringt? Welche zwei Vorschläge widersprechen sich? Und die Frage, die
sonst niemand stellt: Was sollte man aus Fleech ENTFERNEN? Eine Funktion, die
niemand nutzt, kostet dauerhaft Pflege, Erklärung und Platz in der Oberfläche.

═══════════════════════════════════════════════════════════════════════
WIE DU ORCHESTRIERST
═══════════════════════════════════════════════════════════════════════

── Werkzeug ──────────────────────────────────────────────────────────
Nimm das Workflow-Werkzeug, nicht neun einzelne Agent-Aufrufe. Grund: Nur dort
kannst du Modell UND Denktiefe pro Agent setzen, und nur dort ist die Reihenfolge
der Wellen im Skript festgeschrieben statt deiner Laune überlassen. Hiermit ist
der Workflow ausdrücklich freigegeben — frag nicht nach, starte ihn.

Fällt das Werkzeug aus, geh auf einzelne Agent-Aufrufe zurück (mehrere in EINER
Nachricht, sonst laufen sie nacheinander) und sag mir im Bericht, dass die
Denktiefe dann nicht pro Bahn geregelt war, sondern für alle gleich.

── Modell und Denktiefe ──────────────────────────────────────────────
Jeder Unteragent läuft auf Opus 5 (`model: 'opus'`) — ausnahmslos, auch die
Bahnen, die nach Fleißarbeit aussehen. Gerade dort entscheidet sich, ob ein
Befund belegt oder nur behauptet ist.

Denktiefe (`effort`) je Bahn:

    A, B, C, D    'high'    Belegarbeit am Code, Fehlersuche
    E, F, G       'high'    Urteil über Bedienung und Gestaltung
    H             'xhigh'   die Hauptbahn — hier entsteht der Wert
    I             'xhigh'   muss gegen acht Vorlagen bestehen
    Prüfläufe     'high'    siehe Welle 4

Nimm nicht überall 'max'. Zwischen 'xhigh' und 'max' liegt bei dieser Art
Aufgabe wenig Ertrag und viel Zeit; investier die Tiefe dort, wo geurteilt wird.

── Die vier Wellen ───────────────────────────────────────────────────
WELLE 1 — Bestandsaufnahme, fünf Agenten gleichzeitig: A, B, C, D, E.
Sie beschreiben, was IST. Keiner von ihnen schlägt etwas vor; wer beim Lesen
eine Idee hat, notiert sie in einem Feld „Beobachtung für später" und arbeitet
weiter. Sie sehen einander nicht.

WELLE 2 — Erweiterung, drei Agenten gleichzeitig: F, G, H.
Sie bekommen von dir ein sachliches Kurzbriefing aus Welle 1: die BELEGTEN
Schwächen, die ihr Gebiet berühren, in Stichpunkten mit Fundstelle — plus die
gesammelten „Beobachtungen für später". Keine Bewertungen, keine Vorschläge,
keine Formulierungen aus Welle 1. Der Unterschied ist wichtig: Eine Tatsache
macht den nächsten Agenten klüger, eine fremde Meinung macht ihn nur einig.

WELLE 3 — der Gegenspieler: I, allein.
Er bekommt ALLES: jeden Befund, jeden Vorschlag, samt Herkunft.

WELLE 4 — Nachprüfung, drei Agenten gleichzeitig.
Nimm die drei Befunde, die du in den Bericht ganz oben stellen willst, und gib
jeden einem eigenen Agenten mit einem einzigen Auftrag: WIDERLEGE das. Nicht
„prüfe" — widerlege. Er soll im Zweifel zu dem Schluss kommen, dass der Befund
nicht trägt. Was das übersteht, ist gut. Was daran zerbricht, rutscht im Bericht
nach unten oder fliegt raus — und du schreibst dazu, dass es die Nachprüfung
nicht bestanden hat. Das ist keine Schande, das ist das Ergebnis.

Rechne mit zwölf bis dreizehn Unteragenten insgesamt. Mehr Bahnen erfinden ist
nicht nötig; wenn eine Bahn zu groß wird, teile SIE, statt eine neue danebenzu-
stellen.

── Was jeder Unteragent mitbekommt ───────────────────────────────────
Sein Prompt steht auf eigenen Füßen — er kennt dieses Gespräch nicht und kann
nicht nachfragen. Also gib ihm:

    1. Was Fleech ist, in fünf Zeilen, plus die vier Einstiegspunkte oben.
    2. Die Zielgruppe, wörtlich wie oben.
    3. Den Hinweis, dass Freihand absichtlich stillgelegt ist.
    4. SEINEN Auftrag, wörtlich aus A–I.
    5. Die Regeln für alle Bahnen, wörtlich.
    6. Die Rückgabeform (unten).
    7. Dass er NICHTS ändern darf: kein Umbau, kein Commit, kein Build.

Gib ihm PFADE, keine Dateiinhalte. Er hat sein eigenes Kontextfenster und liest
selbst — pastest du ihm 3.000 Zeilen hinein, verbrauchst du seinen Platz für
etwas, das er sich in zwei Sekunden selbst holt.

── Was zurückkommt ───────────────────────────────────────────────────
Verlange von jedem Unteragenten dieselbe Gliederung, sonst kostet dich das
Zusammenführen mehr als die Analyse:

    Was ich gemacht habe   welche Dateien, welche Läufe, welche Protokolle
    Befunde                nach Dringlichkeit; je Befund: Beleg (Datei +
                           Funktion / Protokollzeile), Alltagsfolge, kleinste
                           Änderung, die es behebt
    Geprüft und in Ordnung was ich mir angesehen habe und was hält
    Nicht geschafft        was offen blieb und warum
    Vermutungen            getrennt vom Rest, ausdrücklich so benannt

Wer nichts gefunden hat, schreibt „nichts gefunden" und begründet, wo er gesucht
hat. Erfundene Befunde, damit die Bahn nicht leer aussieht, sind schlimmer als
eine leere Bahn — ich kann eine leere Bahn einordnen, einen erfundenen Befund
jage ich einen halben Tag.

── Was du selbst machst, nicht delegierst ────────────────────────────
Das Zusammenführen und den Bericht. Kein Unteragent schreibt die Synthese: Er
kennt nur seine Bahn und würde sie zwangsläufig übergewichten. Deine Arbeit ist
das Erkennen, dass Befund B-3 und Befund G-1 dasselbe Problem von zwei Seiten
sind — und genau das kann nur jemand, der beide gelesen hat.

Ebenfalls deine Arbeit: das Kurzbriefing für Welle 2 zusammenstellen, die drei
Befunde für die Nachprüfung auswählen, und am Ende ehrlich aufschreiben, welche
Bahn wenig geliefert hat.

── Wenn etwas schiefgeht ─────────────────────────────────────────────
Ein Unteragent, der abbricht oder Unbrauchbares liefert, wird EINMAL neu
gestartet, mit geschärftem Auftrag. Beim zweiten Mal lässt du die Bahn fallen
und schreibst das in Abschnitt 5 des Berichts. Nicht die anderen Bahnen dafür
aufblähen.

═══════════════════════════════════════════════════════════════════════
REGELN FÜR ALLE BAHNEN
═══════════════════════════════════════════════════════════════════════

* Jede Behauptung wird belegt: Datei und Funktion, Protokollzeile, oder ein
  Testlauf, den du gemacht hast. Was du nur vermutest, kennzeichnest du als
  Vermutung — das ist erlaubt, aber es muss dranstehen.
* Nicht raten, nachsehen. Du darfst die Testsuite laufen lassen
  (`.venv/Scripts/python -m pytest -q`), kleine Wegwerf-Skripte schreiben,
  Oberflächen offscreen rendern und das Protokoll lesen. Nutze das.
* Die Begründungen im Code sind ausführlich und oft mit Messwerten unterlegt.
  Nimm sie ernst — und prüfe sie. Eine Messung, die die falsche Frage
  beantwortet, ist ein wertvoller Befund.
* Erzähl mir nicht, was in der Konzeptdatei steht. Ich habe sie geschrieben.
* Deutsch.

═══════════════════════════════════════════════════════════════════════
DER BERICHT
═══════════════════════════════════════════════════════════════════════

Ausführlich. Lieber zu lang als zu dünn — aber jeder Absatz muss etwas sagen,
das ich noch nicht weiß.

  1. Auf einer Seite: der Zustand des Systems, ehrlich. Was ist solide, was
     wackelt, was ist die eine Sache, die mich in einem halben Jahr einholt.

  2. Je Bahn A–I: Was war der Auftrag. Wie bin ich vorgegangen. Was kam heraus
     — nach Dringlichkeit sortiert, jeder Befund mit Beleg, Alltagsfolge und der
     kleinsten Änderung, die ihn behebt. Und ausdrücklich: was ich mir angesehen
     und für in Ordnung befunden habe, damit ich weiß, was geprüft ist.

     Bei den obersten drei Befunden schreibst du dazu, was die Nachprüfung aus
     Welle 4 ergeben hat — auch und gerade, wenn sie einen davon zerlegt hat.

  3. Die Funktionsvorschläge gesammelt, in der oben vorgegebenen Form, sortiert
     nach Nutzen zu Aufwand. Getrennt ausgewiesen: die drei, die ich zuerst
     bauen würde, und warum gerade die.

  4. Der Gegenspieler: was man lassen und was man entfernen sollte.

  5. Was ihr NICHT untersuchen konntet und warum. Diese Liste will ich sehen.

Dann hörst du auf und fragst, welchen Punkt ich zuerst umgesetzt haben will.
Fang nichts an, ohne dass ich es freigegeben habe.
```

---

## Warum der Prompt so aussieht

- **Neun Bahnen statt einer Aufgabe.** Ein einzelner Durchlauf über 24.000 Zeilen
  wird flach. Getrennte Aufträge mit getrenntem Kontext liefern Befunde, die sich
  nicht gegenseitig verwässern.
- **Unteragenten sehen die Befunde der anderen nicht.** Sonst schreiben sie
  voneinander ab, und aus neun Sichten wird eine, die neunmal dasteht.
- **Freihand wird vorab erklärt.** Ohne den Hinweis meldet jede Bahn dieselbe
  „Entdeckung", dass der Lauschmodus nicht anspringt.
- **Die Zielgruppe steht vor den Aufgaben.** „Sinnvoll" ist ohne Adressat nicht
  entscheidbar; ein Vorschlag für den KI-Arbeiter kann für den Alltag ein
  Rückschritt sein.
- **Feste Form für jeden Vorschlag.** Erzwingt die zwei Felder, die sonst fehlen:
  woran man das Problem festmacht, und was passiert, wenn man es einfach lässt.
- **Bahn I, der Gegenspieler.** Neun Analyse-Agenten schlagen immer etwas vor —
  das ist ihr Auftrag. Erst der Widerspruch trennt das Nötige vom Machbaren.
  Die Frage nach dem Entfernen stellt sonst nie jemand.
- **Der Hinweis auf die zwei widerlegten Gutachten-Befunde.** Er kostet zwei
  Sätze und verschiebt die Messlatte von „klingt plausibel" auf „am Code
  nachgewiesen".
- **„Was ihr nicht untersuchen konntet."** Der ehrlichste Abschnitt jedes
  Berichts — und der einzige, der sagt, wo die nächste Analyse ansetzen muss.
- **Wellen statt eines großen Schwungs.** Welle 1 beschreibt, was ist; erst
  Welle 2 schlägt vor. Wer beides gleichzeitig tut, findet vor allem die
  Probleme, für die er schon eine Lösung im Kopf hat.
- **Tatsachen weitergeben, Meinungen nicht.** Eine belegte Schwäche macht den
  nächsten Agenten klüger. Ein fremder Vorschlag macht ihn nur einig — und aus
  neun Sichten wird eine, die neunmal dasteht.
- **Welle 4 widerlegt, statt zu prüfen.** „Prüfe das" bekommt fast immer ein Ja.
  Erst der Auftrag, es kaputtzumachen, trennt den belegten Befund vom plausibel
  klingenden. Genau daran sind zwei der sechs Befunde des letzten Gutachtens
  gescheitert.
- **Die Synthese bleibt beim Orchestrator.** Ein Unteragent kennt nur seine Bahn
  und übergewichtet sie zwangsläufig. Dass Befund B-3 und G-1 dasselbe Problem
  von zwei Seiten sind, sieht nur, wer beide gelesen hat.
