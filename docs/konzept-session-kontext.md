# Konzept: Session-Kontext über mehrere Diktate

> **Status: umgesetzt in v1.11.0** — alle drei Entscheidungen fielen wie empfohlen
> (nur Lese-Kontext, 15 min Konstante, Session-Punkt in der Pille).

> Welle-3-Punkt 15 aus dem [Härtungs-Plan](planung-haertung.md). Dieses Dokument ist
> die geforderte Vorarbeit: Es legt fest, was der Session-Kontext können soll, was er
> bewusst NICHT können soll, und welche Entscheidungen vor der Umsetzung zu treffen
> sind. **Es wird erst gebaut, wenn die offenen Entscheidungen (unten) geklärt sind.**

---

## 1. Ausgangslage: Was heute passiert

Der `DocumentTracker` ist Fleechs einzige Kontext-Quelle — fremde Felder können wir
nicht lesen. Er sammelt alles, was Fleech selbst in das aktuelle Fenster diktiert hat,
und leistet damit zweierlei:

1. **Kontext für den Befehls-Modus** (die letzten ~600 Zeichen gehen als
   KONTEXT-Block an das Befehls-Modell).
2. **Ersetzungs-Scopes** (`last_sentence`, `last_paragraph`, `whole_document`,
   `dictated`) — aufgelöst als exakte End-Abschnitte des Puffers, ersetzt per
   Backspaces + Neueinfügen.

Der Puffer stirbt beim **Fensterwechsel** (`sync_window`). Wer also in Mail A
diktiert, kurz in den Browser schaut und zurückkehrt, hat aus Fleechs Sicht ein
leeres Feld vor sich: „Kimono, mach den letzten Satz formeller" schlägt fehl,
obwohl der Satz sichtbar im Feld steht.

Zweite Lücke: Der Scope `dictated` meint nur den **allerletzten** Block. „Ersetze
das, was ich davor diktiert habe" ist nicht ausdrückbar.

## 2. Der Kern des Konzepts: Zwei Fähigkeiten, zwei Risikoklassen

Die entscheidende Einsicht: **Kontext lesen und Text ersetzen sind nicht gleich
gefährlich.**

- **Kontext wiederherstellen** (lesen): Kehrt der Nutzer zu einem Fenster zurück,
  bekommt das Befehls-Modell wieder den alten KONTEXT-Block. Schlimmster Fehlerfall:
  Das Modell versteht einen Bezug falsch — die bestehenden Guards (Plausibilität,
  Längendeckel, Lösch-Schutz) greifen wie immer. **Risiko: niedrig.**
- **Ersetzungen über eine Rückkehr hinweg** (schreiben): `replace_tail` sendet
  blinde Backspaces und setzt voraus, dass der Cursor **unmittelbar hinter dem
  eigenen Text** steht. Nach einem Fensterwechsel ist die Cursor-Position unbekannt;
  der Nutzer kann geklickt, getippt, gescrollt haben. Backspaces löschen dann
  **fremden Text, den Fleech nie gesehen hat.** Das ist dieselbe Fehlerklasse wie der
  historische 2701-Zeichen-Verlust — nur ohne jede Möglichkeit eines Guards, weil
  wir das Feld nicht lesen können. **Risiko: hoch, nicht absicherbar.**

**Empfehlung (Kern des Konzepts):** Session-Kontext = Fähigkeit 1 vollständig,
Fähigkeit 2 bewusst **nicht**. Konkret:

- Pro Fenster bleibt der Diktat-Verlauf erhalten (statt beim Wechsel verworfen).
- Nach einer Rückkehr kennt der Befehls-Modus den alten Text wieder: Umformulieren
  **als Anhängen** („Kimono, formuliere den letzten Absatz um und häng die neue
  Fassung an"), Bezüge („mach daraus eine Liste") und die Fortsetzung nach
  „Kimono Ende" funktionieren.
- **Ersetzungs-Scopes bleiben an die ununterbrochene Sitzung gebunden**: Sie lösen
  nur auf, wenn seit der letzten eigenen Injection kein Fensterwechsel lag — exakt
  die heutige Garantie. Ein Befehl, der nach einer Rückkehr ersetzen will, wird wie
  heute abgefangen („Kein eigener diktierter Text im Puffer") und fällt sauber auf
  den Cleanup zurück; es geht nie etwas verloren.

Damit bleibt der Satz aus dem Gesamtkonzept wahr: *Fleech löscht nie Text, dessen
Position es nicht selbst garantiert kennt.*

## 3. Umsetzung (Skizze)

### 3.1 Tracker

`DocumentTracker` bekommt statt eines Einzel-Puffers eine kleine Karte:

```
_sessions: {hwnd: _Session}
_Session:  text: str            # wie heute
           chunks: list[str]    # die letzten N eigenen Blöcke (N = 10)
           last_activity: float # für den Timeout
           dirty: bool          # True nach Rückkehr → Ersetzungen gesperrt
```

- `sync_window()` verwirft nicht mehr, sondern **wechselt** die aktive Session.
  Bei Rückkehr zu bekanntem `hwnd`: Session reaktivieren, `dirty = True` setzen.
- `record_append`/`record_replace`: wie heute, zusätzlich `chunks` pflegen und
  `dirty = False` setzen (nach eigener Injection stimmt die Cursor-Annahme wieder).
- `resolve_scope()`: bei `dirty == True` → `None` (= heutiges Verhalten nach
  Fensterwechsel). `context_tail()` liefert dagegen immer.
- **Speicher-Deckel**: höchstens 8 Sessions, älteste fliegt; pro Session höchstens
  ~8 kB Text. Alles nur im RAM — nichts davon berührt die Historie/SQLite.
- Geschlossene Fenster: tote `hwnd`s werden beim Wechsel aufgeräumt
  (`IsWindow`-Check, Linux: Fenster-Liste).

### 3.2 Timeout

Eine Session, in die länger als **X Minuten** nichts diktiert wurde, verfällt.
Begründung: Je älter der Kontext, desto wahrscheinlicher hat der Nutzer den Text
längst von Hand umgebaut — ein Bezug darauf würde das Befehls-Modell eher in die
Irre führen als stützen. Vorschlag: **X = 15 min**, als Konstante (keine
Einstellung — erst, wenn sich real ein anderer Bedarf zeigt).

### 3.3 Scope „vorheriges Diktat"

Mit `chunks` wird ein neuer Ersetzungs-Scope `previous_dictated` möglich („ersetze
das vorletzte Diktat"). **Empfehlung: NICHT in dieser Runde.** Er braucht eine
Prompt-Erweiterung (Befehls-JSON-Schema), neue Beispiele und ist nur in der
ununterbrochenen Sitzung sicher — der Nutzwert ist unklar, solange niemand ihn
vermisst hat. Die `chunks`-Struktur wird trotzdem angelegt (sie kostet nichts und
der KONTEXT-Block wird damit strukturierter: „[Diktat 1] … [Diktat 2] …").

### 3.4 Sichtbarkeit in der Pille

Ein kleiner **Session-Punkt** neben dem Status-Punkt: sichtbar, wenn für das
aktuelle Fenster gemerkter Kontext existiert; Ton gedämpft (kein Alarm, reine
Information). Tooltip: „Fleech erinnert sich an N Diktate in diesem Fenster
(vor M Minuten)". Kein Punkt = kein Kontext = Befehle beziehen sich auf nichts.
Das beantwortet die sonst unvermeidliche Frage „warum hat der Befehl gerade (nicht)
funktioniert?" ohne Log-Blick.

### 3.5 Tests

- Fenster A → B → A: Kontext wieder da, `resolve_scope` liefert `None` (dirty).
- Nach neuer Injection in A: Ersetzungen wieder möglich.
- Timeout verwirft; Deckel (Sessions/Bytes) greift; tote Fenster werden entsorgt.
- Interleaving wie gehabt (RLock bleibt).

Aufwand geschätzt: Tracker + Tests ~1 Sitzung, Pillen-Punkt + Verdrahtung klein.

## 4. Bewusst nicht Teil dieses Konzepts

- **Ersetzungen nach Rückkehr** (siehe oben — nicht absicherbar).
- **Feld-genaue Sessions** (dasselbe Fenster, zwei Eingabefelder): Die Feld-Identität
  ist fensterübergreifend nicht zuverlässig zu bestimmen (UIA-Element-IDs sind
  flüchtig). Fenster-Ebene ist die ehrliche Granularität; Fehlzuordnungen innerhalb
  eines Fensters betreffen nur den Lese-Kontext, nie Ersetzungen.
- **Persistenz über App-Neustarts**: Der Kontext beschreibt den Live-Zustand fremder
  Felder — nach einem Neustart ist jede Annahme darüber Spekulation.

## 5. Offene Entscheidungen (vor dem Bau zu klären)

1. **Reichweite**: Kontext-only wie empfohlen — oder sollen Ersetzungen nach
   Rückkehr doch möglich sein? (Meine klare Empfehlung: nein, siehe 2.)
2. **Timeout**: 15 min als Konstante in Ordnung?
3. **Pillen-Punkt**: gewünscht, oder lieber ganz ohne sichtbares Signal?

---

*Anschluss-Perspektive: Mit Session-Kontext + Onboarding-Wizard wären alle
geplanten Welle-1-bis-3-Punkte umgesetzt — der natürliche Moment für **Fleech 2.0**
(W4 — Wayland-Portale, Accessibility — bleibt laut Plan anlassgebunden).*
