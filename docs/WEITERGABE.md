# Fleech weitergeben — Schritt für Schritt

Kurzfassung: **Release veröffentlichen** (einmal pro Version) → **Schlüssel ausstellen**
(einmal pro Person) → **Link + Schlüssel schicken**. Alles Weitere macht Fleech beim
Empfänger selbst.

---

## Wie die Zugangskontrolle funktioniert

Zwei Repositories, mit Absicht:

| Repository | Sichtbarkeit | Inhalt |
|---|---|---|
| `FynnXland/fleech` | **privat** | der Quellcode |
| `FynnXland/fleech-releases` | **öffentlich** | nur die Installer-Dateien |

Das Releases-Repo ist öffentlich, damit die Update-Prüfung ohne Zugriffstoken auskommt —
ein Token in einer ausgelieferten EXE wäre ohnehin mit `strings` auslesbar.

**Das heißt: die Installationsdatei kann jeder herunterladen.** Das ist kein Leck,
sondern der Entwurf: Wer Fleech *benutzen* darf, entscheidet der **Lizenzschlüssel**.
Ohne gültigen Schlüssel startet keine Aufnahme — die Sperre sitzt vor dem Mikrofon.
Der Quellcode bleibt privat.

Die Schlüssel sind Ed25519-signiert. In der EXE steckt nur der **öffentliche** Teil
(harmlos, er kann nur prüfen, nicht ausstellen). Signieren kannst nur du.

---

## Schritt 1 — Release veröffentlichen

Nur nötig, wenn seit dem letzten Release etwas dazugekommen ist. Prüfen:

```bash
gh release list --repo FynnXland/fleech-releases
```

Steht dort schon die Version aus `fleech/version.py`, überspring diesen Schritt.

Sonst: Version in [fleech/version.py](fleech/version.py) auf eine **Minor**-Version
hochziehen (`4.8.0`, nicht `4.7.2`) — `release.py` verweigert Patch-Versionen von sich
aus, weil ein Release rund zehn Minuten dauert und 1 GB hochlädt.

```bash
.venv/Scripts/python packaging/release.py
```

Das Skript baut EXE + Installer, bildet die SHA-256, legt das GitHub-Release an und lädt
`FleechSetup-<Version>.exe` hoch (~1 GB). Voraussetzungen prüft es **vorher**, damit der
Fehler nicht erst nach zehn Minuten kommt: Inno Setup 6 und ein angemeldetes `gh`.

Vorher ansehen, ohne hochzuladen:

```bash
.venv/Scripts/python packaging/release.py --dry-run
```

Ist nur der Upload gescheitert, nicht neu bauen — `--no-build` nutzt die vorhandene
Setup-Datei.

---

## Schritt 2 — Schlüssel für die Person ausstellen

**Der einfache Weg:** Doppelklick auf **`Schluessel erstellen.bat`** im Projektordner.
Sie fragt nach dem Namen und der Gültigkeit (Enter = unbefristet), zeigt den Schlüssel
und legt ihn gleich in die **Zwischenablage** — aus einem Konsolenfenster mit der Maus
markiert man leicht ein Zeichen zu wenig, und ein halber Schlüssel scheitert beim
Empfänger ohne erkennbaren Grund.

Auf der Kommandozeile geht es genauso:

```bash
.venv/Scripts/python packaging/issue_key.py "Vorname Nachname"
```

Befristet, wenn du willst:

```bash
.venv/Scripts/python packaging/issue_key.py "Vorname Nachname" --days 365
```

Heraus kommt eine Zeile, die mit `FLEECH-1.` beginnt. Der Name steht **im Schlüssel** und
ist mitsigniert — ändert ihn jemand, bricht die Signatur. Das Skript macht die Gegenprobe
mit genau dem Code, der später beim Empfänger läuft, und meldet „Gegenprobe: gültig".
Nur dann verschicken.

Ein Schlüssel gilt für die Person, nicht für ein Gerät — sie kann ihn auf mehreren
Rechnern eintragen. Wer ihn weitergibt, gibt seinen eigenen Namen mit.

---

## Schritt 3 — Verschicken

Zwei Dinge:

1. **Link:** `https://github.com/FynnXland/fleech-releases/releases/latest`
   (immer die neueste Version, kein Konto nötig)
2. **Der Schlüssel** aus Schritt 2

Beides darf in dieselbe Mail — der Link ist ohnehin öffentlich, geheim ist nur der
Schlüssel.

Dazu die Anleitung [FUER-EMPFAENGER.md](FUER-EMPFAENGER.md): Installation,
Freischalten, erste Schritte, die häufigsten Stolpersteine. Sie ist so
geschrieben, dass man sie unverändert weiterleiten kann — ohne Wissen über
Repositories, Signaturen oder den Build.

---

## Was beim Empfänger passiert

1. **Installieren.** `FleechSetup-<Version>.exe` ausführen. Per-user, **kein Administrator
   nötig**. Läuft schon ein Fleech, beendet der Installer es selbst.
2. **Erster Start.** Fleech zeigt die Einführung und, falls etwas fehlt, die
   Einrichtungsseite: **Ollama-Dienst** (installiert Fleech per `winget` selbst),
   **Sprachmodell** `gemma3:4b` (~3,3 GB) und **Whisper** `large-v3-turbo` — alles mit
   Fortschrittsanzeige im Fleech-Design, kein Terminal. Braucht Internet, aber nur
   dieses eine Mal.
3. **Freischalten.** Einstellungen → **Lizenz** → Schlüssel einfügen. Wer es vergisst,
   bekommt den Dialog automatisch beim ersten Aufnahmeversuch.
4. **Diktieren.** Ab dann läuft alles lokal — kein Audio und kein Text verlässt den
   Rechner.

**Updates** laufen von selbst: Fleech fragt das öffentliche Releases-Repo, prüft die
SHA-256 aus den Release-Notizen gegen die geladene Datei und verwirft sie bei
Abweichung. Kein Token, kein Konto.

**Ohne NVIDIA-Grafikkarte:** Der Build enthält CUDA, Whisper fällt aber auf CPU zurück
(`_fall_back_to_cpu` in [fleech/stt/faster_whisper_stt.py](fleech/stt/faster_whisper_stt.py)).
Das funktioniert, ist aber deutlich langsamer — auf einem fremden Rechner noch nicht
gemessen.

---

## Der private Signaturschlüssel

```
%APPDATA%\Fleech\signing\fleech-signing-key.pem
```

Diese eine Datei ist das ganze Geheimnis. Sie liegt bewusst **außerhalb** des
Projektordners, damit sie weder versehentlich committet noch mitgepackt wird.

- **Geht sie verloren**, kannst du keine neuen Schlüssel mehr ausstellen. Dann bleibt nur:
  neues Paar erzeugen (`issue_key.py --init`), `PUBLIC_KEY_HEX` in
  [fleech/licensing.py](fleech/licensing.py) ersetzen, neu ausliefern — und **alle**
  bisherigen Schlüssel neu ausgeben.
- **Wird sie kopiert**, kann der Empfänger sich selbst beliebige Schlüssel ausstellen.

→ **Sichere sie einmal** (Passwortmanager oder verschlüsselter Datenträger), aber nicht
in ein Repository und nicht in einen Ordner, der irgendwo hin synchronisiert wird.

---

## Einen Schlüssel wieder entziehen

Geht derzeit **nicht**. Die Prüfung ist offline, sie kennt keine Sperrliste — sie kann nur
Signatur und Ablaufdatum prüfen. Wenn das ein Thema wird, ist der pragmatische Weg
`--days 365`: Ein befristeter Schlüssel läuft von selbst aus und wird nur für den
verlängert, der ihn behalten soll.
