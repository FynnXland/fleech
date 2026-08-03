# Änderungen

Was in welcher Version dazugekommen ist — neueste zuerst. Geschrieben für den,
der Fleech **benutzt**, nicht für den, der den Code liest: technische
Begründungen stehen in den Commit-Nachrichten.

Versionen mit einer dritten Stelle (`4.9.1`) sind Kleinigkeiten und werden nicht
einzeln veröffentlicht — sie sind in der nächsten Minor-Version enthalten. Der
Abschnitt einer veröffentlichten Version landet automatisch in den
GitHub-Release-Notizen (`packaging/release.py`).

---

## 5.1.0 — 2026-08-02

**Fleech merkt sich deine Fachbegriffe.** Je Programm und Fenster lernt es die
Wörter mit, die dort vorkommen — `MCP-Server`, `PySide6`, `Cauchy-Schwarz-Ungleichung`, `x_3` — und gibt sie beim nächsten Diktat als Hinweis an die
Erkennung. Genau die Begriffe, an denen sich Whisper sonst verhört, kommen damit
richtig geschrieben an. Das überlebt jeden Neustart.

**Der Bestand wird sofort genutzt:** Beim ersten Start nach dem Update lernt
Fleech einmalig aus deinem bisherigen Verlauf, statt bei null anzufangen. Läuft
im Hintergrund, der Start verzögert sich nicht.

Zwei Ebenen, ohne dass du etwas anlegen musst: Was im konkreten Fenster gilt,
steht vorn; darunter der Bestand des ganzen Programms. Der Fenstertitel wird dafür
in seine Teile zerlegt — was stabil bleibt (das Projekt), sammelt viel; was
wechselt (der Dateiname), fällt von selbst zurück.

**Was NICHT passiert:** Es geht kein Inhalt an die KI. Eine mitgegebene
Projekt-Zusammenfassung wäre mächtiger, würde aber jedes Diktat verlangsamen und
der KI Material geben, aus dem sie ergänzen kann — genau die Halluzinationen,
gegen die vier Filter stehen. Vokabular kann nichts erfinden: Es verschiebt nur
die Wahrscheinlichkeit, ein tatsächlich gesprochenes Wort richtig zu schreiben.
Gemessen: 0,6 ms je Diktat.

Unter **Einstellungen → Ausgabe** steht, was gelernt wurde („76 Begriffe in 7
Programmen — claude.exe: GitHub, MCP-Server …"), dazu ein Schalter und
„Gelerntes vergessen".

**Umbenannt:** Das Profil „Zusammenfassen" heißt jetzt **„Stichpunkte"** — wie
das Format, das es erzeugt. Der alte Name versprach eine Zusammenfassung, während
der Prompt seit 4.10.0 das Gegenteil tut (nichts weglassen, nur die Sprechweise
aufräumen).

## 5.0.0 — 2026-08-02

**Die erste Fassung, die für jemand anderen gebaut ist.** Technisch bricht nichts
— die große Zahl markiert die Schwelle: Bis hierher lief Fleech auf einem
Rechner, ab hier wird es weitergegeben. Wer von 4.x kommt, findet vor allem die
App-Zuordnung an einer neuen Stelle (eigene Seite „Apps" statt in den Profilen);
bestehende Zuordnungen wandern unverändert mit.

Enthalten sind die Kleinigkeiten aus 4.10.1 und 4.10.2 (siehe unten): die
Profil-Anzeige unter der Pille, die sich schließende Auswahlliste und das Profil,
das der App sofort folgt statt erst nach drei Sekunden.

**Für den Empfänger** braucht es nur zwei Dinge: die Setup-Datei aus diesem
Release und einen persönlichen Lizenzschlüssel. Beim ersten Start richtet Fleech
sich selbst ein — Ollama, Sprachmodell, Spracherkennung, mit Fortschrittsanzeige
statt Terminal. Danach läuft alles lokal: weder Audio noch Text verlassen den
Rechner. Der ganze Ablauf steht in [docs/WEITERGABE.md](docs/WEITERGABE.md).

**Behoben (Werkzeug):** Schlug das Laden des Signaturschlüssels fehl, erschien ein
roher Fehlerbericht — der sich las, als sei der Schlüssel zerstört. Er wird jetzt
mehrfach versucht, und die Meldung unterscheidet klar zwischen „die Datei ist in
Ordnung, versuch es gleich nochmal" und einer wirklich beschädigten Datei.

## 4.10.2 — 2026-08-02 · nicht einzeln veröffentlicht

**Das Profil folgt der App jetzt sofort.** Fleech fragte das Vordergrundfenster
nur alle drei Sekunden ab — wer in eine App tabbte und gleich den Hotkey nahm,
bekam bis zu drei Sekunden lang die Profile der vorigen App. Genau so gemeldet:
„wenn ich nach Chrome tabbe, kann ich zwischen allen Chrome-Profilen wechseln,
und wenn ich wieder in Claude bin, immer noch die vier."

Der Drei-Sekunden-Takt bleibt, wo er hingehört (Lautstärke-Absenkung,
Spiel-Erkennung). Alles, was an einem Tastendruck hängt, fragt jetzt direkt ab.

Wichtiger noch als die Auswahlliste ist der **Aufnahmestart**: Von der App, die
dort festgehalten wird, hängt ab, welches Profil den Text formt. Mit dem alten
Takt konnte der Text im richtigen Fenster landen, aber im falschen Format.

Während einer laufenden Aufnahme gilt unverändert die App, in der gestartet
wurde — auch wenn man zwischendurch woanders hin wechselt. Dorthin kehrt der
Cursor am Ende zurück, dort landet der Text.

## 4.10.1 — 2026-08-02 · nicht einzeln veröffentlicht

Die Profil-Anzeige unter der Pille **überlappte sie**, wenn die Pille tief am
unteren Bildschirmrand steht. Sie ist jetzt dieselbe Blase wie die
Live-Transkription, nur unterhalb statt oberhalb — gleiches Aussehen, gleicher
Abstand, keine eigene Positionsrechnung mehr, die abweichen kann.

Die **Profil-Auswahlliste schließt jetzt bei einem Klick daneben**, auch wenn
dieser in eine andere Anwendung geht. Vorher blieb sie stehen, bis man etwas
auswählte oder Escape drückte: Die Liste nimmt bewusst nie den Fokus (sonst wäre
das Textfeld weg, in das gleich eingefügt werden soll) — damit erfuhr Fleech von
solchen Klicks gar nichts.

## 4.10.0 — 2026-08-02

**Neue Seite „Apps"** — vierter Punkt in der Navigation. Links die Anwendungen,
in der Mitte welches Profil Fleech dort automatisch nimmt, rechts zwischen
welchen Profilen der Profil-Hotkey dort wechselt. In Claude also nur zwischen
„KI-Prompt" und „Stichpunkte" durchtippen statt durch alle acht. Die Zuordnung
stand vorher auf der Profilseite andersherum („welche Apps gehören zu diesem
Profil") — bestehende Zuordnungen bleiben unverändert erhalten.

**Feinere Regeln je Fenstertitel**: derselbe Prozess in zwei Kontexten, z. B.
`Code.exe` allgemein → Geschäftlich, aber Fenster mit „Fleech" im Titel → Privat.

**Suchfelder** bei den Anwendungen und bei den Profilen. Gesucht wird über die
ganze Zeile — „stichpunkte" findet also auch die Apps, die auf dieses Profil
zeigen.

**Diktierzeit** in den Insights, unter dem Tacho: wie lange insgesamt gesprochen
wurde und im Schnitt je Diktat.

**„Stichpunkte" fasst nicht mehr zusammen.** Das Profil hieß „Zusammenfassen" und
tat genau das — gewünscht war das Gegenteil: jede genannte Sache bekommt einen
Stichpunkt, nichts wird weggelassen. Entfernt wird nur die Sprechweise
(Wiederholungen, Anläufe, Umwege).

**Einstellungen überleben ein Update.** Bisher standen nach einem Update Hotkeys,
Profile und der Lizenzschlüssel wieder auf Vorgabe. Die Datei wird jetzt so
geschrieben, dass es sie immer entweder alt oder neu gibt, nie halb; zusätzlich
liegt die vorige Fassung als Sicherung daneben, aus der Fleech sich selbst heilt.

**Behoben**
- Fleech fror ein, sobald man ohne Lizenzschlüssel eine Aufnahme startete.
- Gelöschte Hotkeys blieben nicht gelöscht — beim nächsten Öffnen der
  Einstellungen stand wieder die Vorgabe da.
- Die Profil-Anzeige sprang bei wenig Platz über die Pille und verdeckte die
  Live-Transkription. Sie bleibt jetzt immer darunter.
- Zwei Einblendungen unter der Pille lagen übereinander: der Pause-Tooltip und
  die Modus-Zeile („Fokus …, Eingriff …") sind entfallen. ✓ und ✕ behalten ihre
  Erklärung.
- „App-Standard" statt „Automatisch (nach App)".

**Weitergabe**: `Schluessel erstellen.bat` im Projektordner — Doppelklick, Name
eintippen, der Schlüssel liegt in der Zwischenablage. Der ganze Ablauf steht in
[docs/WEITERGABE.md](docs/WEITERGABE.md).

## 4.6.1 — 2026-07-31 · nicht einzeln veröffentlicht

Drei Anzeigefehler der Profilseite: doppelter Name („E-Mail · E-Mail"), ein
Kategoriepunkt in der Akzentfarbe (las sich wie „ausgewählt") und eine rechte
Spalte, in der die Beschriftungen weit von ihren Bedienelementen standen.

## 4.6.0 — 2026-07-31

**Profil „Zusammenfassen"**: destilliert das Gesagte in knappe Stichpunkte, ohne
Rolle und ohne erfundenen Kontext.

**Schnellwechsel-Auswahl**: Profile lassen sich aus Punkt, Hotkey und
Auswahlliste ausblenden — mit acht Profilen war Durchschalten sonst mühsam. Sie
bleiben in der Liste sichtbar und sind als ausgeblendet gekennzeichnet.

**Ausgabeformat in der Übersicht**: farbiger Punkt und Kurzname hinter dem
Profilnamen. Die Frage „was macht dieses Profil?" beantwortet jetzt die Liste.

**Einfach/Erweitert**: Eingriff, Safe-Word und automatisches Absenden liegen
hinter einem Schalter. Ein Profil besteht sonst aus Name, Ausgabeformat und
Schnellwechsel.

Die Pille rastet beim Ziehen an Bildschirmmitte und -rändern ein.

## 4.5.1 — 2026-07-31 · nicht einzeln veröffentlicht

Die Profil-Kapsel blieb nach dem Umschalten dauerhaft stehen, saß an einer
unruhigen Position und zeigte den „Anwendung startet"-Mauszeiger. Nebenbei
funktionierte damit das Halten des Profil-Hotkeys erstmals wirklich.

## 4.5.0 — 2026-07-31

**Profil-Hotkey**: Tippen schaltet zum nächsten Profil, Halten öffnet eine
Auswahlliste am Mauszeiger. Ohne Vorbelegung ausgeliefert — die sinnvollste Taste
ist eine Maus-Zusatztaste, und die ist je nach Maus anders.

**Escape löscht** eine Hotkey-Belegung. Vorher brach Escape nur ab, gelöscht
wurde mit Entf — gesucht wurde Escape.

Das zuletzt gewählte Profil bleibt über Neustarts aktiv.

## 4.4.1 — 2026-07-31 · nicht einzeln veröffentlicht

Vierter Filter gegen angehängten Text, den niemand gesagt hat — diesmal
fremdsprachiger Wortsalat am Diktatende.

## 4.4.0 — 2026-07-31

**Profile bestimmen das Ausgabeformat**, nicht mehr nur die Glättung. Zwei neue
Standardprofile:

- **E-Mail** — Anrede, Absätze, Grußformel, gehobenerer Ton. Der Absendername
  kommt aus den Einstellungen; ohne ihn endet die Mail mit der Grußformel.
- **KI-Prompt** — zieht Wiederholungen zusammen und dampft Herleitungen ein.
  Gemessen: 92 gesprochene Wörter → 70, ohne eine Anforderung zu verlieren.

Schlägt ein Format fehl, kommt das normale Diktat — der Text geht nie verloren.

**Veröffentlicht wird nur noch bei Minor-Versionen.** Installer bauen und 1 GB
hochladen dauert zehn Minuten; Kleinigkeiten sammeln sich und kommen mit der
nächsten Minor-Version.

## 4.3.0 — 2026-07-31

**Formel-Erkennung gehärtet.** Sie hat Wörter zerstört: „3D-Model" wurde zu
`$3D -$Model`, „Combat-Log-Dummy" zu `Combat$-\log -$Dummy`. Ein Bindestrich ohne
Leerzeichen zwischen zwei Wortzeichen gilt jetzt nicht mehr als Minus, und ein
nacktes Minus trägt eine Formel erst ab vier Operanden. An 1137 echten Diktaten
kalibriert.

**Gesprochene Zeichen**: „Slash", „Hashtag", „Unterstrich" und Ähnliches werden
zum Zeichen, nicht zum Wort.

## 4.2.0 — 2026-07-31

Der Pause-Knopf wandert auf die rechte Insel — in der Mitte hatte er die
Symmetrie der Pille zerstört. Der Befehls-Knopf (») ist aus der Pille entfernt,
er wurde nie benutzt; das gesprochene Safe-Word bleibt unberührt.

## 4.1.0 — 2026-07-30

**Pause während der Aufnahme** (Knopf in der Pille oder Hotkey). Spricht jemand
dazwischen, hält die Aufnahme an und läuft danach im selben Diktat weiter. Die
Waveform geht in die Punktreihe — flache Balken sähen aus wie „du bist nur leise".

## 4.0.0 — 2026-07-30

**Lizenzschlüssel.** Fleech diktiert nur mit gültigem Schlüssel; die Sperre sitzt
vor dem Mikrofon, es wird also gar nichts erst aufgenommen. Geprüft wird offline.

**Automatische Updates** über ein öffentliches Releases-Repository, während der
Quellcode privat bleibt. Keine Installation braucht dafür einen Zugriffstoken.

Ehrlich benannt: Eine lokale Prüfung lässt sich herauspatchen. Sie verhindert das
Weiterreichen, nicht das Reverse Engineering.
