# Änderungen

Was in welcher Version dazugekommen ist — neueste zuerst. Geschrieben für den,
der Fleech **benutzt**, nicht für den, der den Code liest: technische
Begründungen stehen in den Commit-Nachrichten.

Versionen mit einer dritten Stelle (`4.9.1`) sind Kleinigkeiten und werden nicht
einzeln veröffentlicht — sie sind in der nächsten Minor-Version enthalten. Der
Abschnitt einer veröffentlichten Version landet automatisch in den
GitHub-Release-Notizen (`packaging/release.py`).

---

## 5.11.0 — 2026-08-18

Das erste Release nach der Tiefenanalyse vom 17./18. August: vierzehn Prüf-Agenten
haben Code, Protokoll und den echten Verlauf durchgesehen, dann wurden ihre Befunde in
zwölf Blöcken umgesetzt (5.10.3 bis 5.10.5, alle in dieser Version enthalten). Kurz,
was du im Alltag merkst — Einzelheiten stehen in den Abschnitten der drei
Zwischenversionen darunter:

- **Die Einstellungsdatei geht nicht mehr verloren.** Gleichzeitiges Speichern kann
  sie nicht mehr zerstören; steht sie nach einem Unfall plötzlich auf Werkseinstellung
  (Lizenz weg, Hotkey F9), holt Fleech beim Start die letzte gute Fassung zurück.
- **Der Verlauf sagt, warum.** Jeder Eintrag kennt den Grund eines Rückfalls, das
  Profil und das Fenster; verworfene Wörter werden aufgehoben; der Verlauf lässt sich
  nach Wort, Programm und Zeitraum durchsuchen und als Markdown speichern. Das
  Protokoll trägt ein Datum und rotiert.
- **Profile tun, was sie versprechen — und man sieht, welches gilt.** Das
  Stichpunkte-Profil bildet Stichpunkte, „direkt abschicken" wirkt in KI-Prompt und
  Stichpunkte, der Schnellwechsel überspringt das Standardprofil (das legte bisher
  unbemerkt die App-Zuordnung still), der Ring an der Pille zeigt das Profil der App,
  in die du diktierst, die Apps-Seite sagt live „Wenn du jetzt diktierst …", die
  Sprache ist je Profil einstellbar, „Jetzt aktiv" steht oben auf der Profilseite.
- **Drei neue Handgriffe rund um Profile:** Profile exportieren/importieren (nur
  Profile, kein Lizenzschlüssel — zum Weitergeben), „Aktuellen Titel übernehmen"
  statt Abtippen (mit Vorschlägen für den stabilen Teil des Titels), und eine Karte,
  die für stark genutzte Programme ohne Profil eine Zuordnung vorschlägt — nie
  automatisch, „Nicht mehr fragen" ist einen Klick entfernt.
- **Wächter, die stimmen.** Uhrzeiten („18.50 Uhr" → „18:50 Uhr") kosten keinen
  Fehlversuch mehr; „Strong" prüft wieder Zahlen und Verneinungen; leere
  KI-Antworten und verlorene Formeln werden ehrlich als Rückfall gemeldet;
  Endlosschleifen im Text („um, um, um, um, um") werden gekürzt und gemeldet;
  „Raute", „Unterstrich", „Schrägstrich" bleiben normale Wörter.
- **Aufnahmeweg ohne Klemmen.** Diktier-Hotkeys auf Makro-/G-Tasten funktionieren
  zuverlässig; gehaltene Tasten lösen nicht doppelt aus; „Kein Ton vom Mikrofon"
  warnt nach vier Sekunden Stille noch während des Diktats (Schwelle am Gerät
  geprüft); ein fehlendes Mikrofon und eine nicht laufende lokale KI werden gemeldet;
  ein kopiertes Bild bleibt in der Zwischenablage; beim Beenden werden andere Apps
  wieder laut; die letzte Aufnahme lässt sich aus dem Tray noch einmal erkennen oder
  als WAV sichern.
- **Insights mit ehrlichen Zahlen.** Median statt Mittelwert, Buchvergleich auf die
  Lebenszeit, keine Banalitäten bei kurzen Zeiträumen; „Als Regel übernehmen" schlägt
  nur noch echte Erkennungsfehler vor und fragt bei Schreibvarianten
  („Cloud-Code 18× · Claude Code 10× — welche stimmt?"); gelerntes Vokabular ist
  einzeln vergessbar.
- **Texte, die stimmen.** Einführung, Hilfetexte und die Weitergabe-Dokumentation
  sagen jetzt, was die App tut (kein toter Formel-Hotkey, „Anstupsen" als dritter
  Bedienmodus, ehrliche Speicher- und Wartezeiten, „?" erklärt alle Optionen).

**Entfernt, weil ungenutzt** — belegt am eigenen Verlauf: die **Textbausteine**
(in 1399 Diktaten kein einziger angelegt und kein wiederkehrender Text, aus dem einer
geworden wäre; die Einsprech-Probe für Wörterbuch-Einträge bleibt), die
**Freihand-Oberfläche** (der Modus ist seit 5.10.1 stillgelegt; der Code bleibt
eingefroren, „Anstupsen" ist der Nachfolger, der Sprechpause-Regler steht jetzt beim
Bedienmodus) und der Schalter **„Adaptive Geschwindigkeit"** (er bewirkte seit
Version 3.5 nichts mehr — es gibt nur ein Modell; die kurze Route für kurze Diktate
bleibt an).

---

## 5.10.5 — 2026-08-18

*Nicht einzeln veröffentlicht.* Dritte Runde aus der Tiefenanalyse: Profile werden
sichtbar, das Mikrofon meldet sich, wenn es nichts liefert, und drei Funktionen, die
aus dem eigenen Verlauf etwas machen.

**Du siehst, welches Profil gilt.** Der Ring am Punkt der Pille zeigt jetzt das
Profil, das in der App gilt, in die du gerade diktierst — nicht mehr nur das von Hand
gewählte; wechselt es beim Aufnahmestart, erscheint der Name kurz daneben. Die Seite
„Apps" sagt oben mitlaufend, was ein Diktat jetzt ergäbe: Anwendung, Fenstertitel,
das daraus aufgelöste Profil samt Regel, Ausgabeformat, Eingriff und Sprache. Die
Anwendungsliste dort ist nach diktierten Wörtern sortiert, die meistgenutzte App ist
vorgewählt, zugewiesene Programme, die es nicht zu geben scheint („noch nie
gesehen"), stehen farbig ganz oben — ein Tippfehler fällt sofort auf. Beim Anlegen
einer Titel-Ausnahme steht das Profil vorn, das in dieser App ohnehin gilt; eine
Ausnahme auf das Standardprofil ist jetzt möglich und wirkt. Oben auf der Profilseite
wählst du, welches Profil gerade gilt — ohne laufende Aufnahme und ohne Hotkey. Und
die Diktiersprache lässt sich je Profil einstellen (deutscher Prompt im Chat,
englischer Kommentar in der IDE). Sind Profile global aus, sagt der Punkt das,
statt zu wechseln.

**„Kein Ton vom Mikrofon"** — nach vier Sekunden ohne Ton wird der Punkt an der
Pille rot und eine Blase sagt es, noch während du sprichst. Bisher merkte man es erst
am leeren Ergebnis, im schlimmsten Fall nach zweieinhalb Minuten Rede. Die Warnung
stoppt nichts und verschwindet, sobald wieder Ton ankommt. Aussetzer der
Audio-Schnittstelle stehen jetzt im Protokoll.

**Der Verlauf lässt sich durchsuchen** — nach Wörtern (auch nach solchen, die die
Bereinigung entfernt hat), nach Programm und Zeitraum, statt nur der letzten 40
Einträge; die Treffer lassen sich als Markdown-Datei speichern (der Knopf sagt, dass
darin der volle Wortlaut unverschlüsselt steht).

**Schreibweisen statt Grammatik.** Die Vorschlagskarte in den Insights fragt jetzt:
„Cloud-Code 18× · Claude Code 10× — welche Schreibweise stimmt?" Beide Seiten sind
gleichwertige Knöpfe; die Antwort wird eine Wörterbuch-Regel, und Fleech vergisst
die falsche Form auch im Gedächtnis, damit sie sich nicht über die Erkennung selbst
weiterträgt. Gelerntes Vokabular lässt sich unter Einstellungen → Textersetzung
jetzt auch einzeln vergessen.

**Die letzte Aufnahme bleibt im Arbeitsspeicher.** Über das Tray-Menü lässt sie sich
noch einmal erkennen (wenn nichts ankam oder Ollama gerade nicht lief) oder als
WAV-Datei sichern — auch dann, wenn gar kein Text herauskam. Nie auf Platte, außer
du sicherst sie ausdrücklich.

---

## 5.10.4 — 2026-08-18

*Nicht einzeln veröffentlicht.* Zweite Runde aus der Tiefenanalyse: Der Verlauf
kann jetzt „warum" beantworten, der Aufnahmeweg verliert seine Klemmen, die Insights
zeigen ehrliche Zahlen.

**Der Verlauf sagt, warum ein Diktat nicht glattlief.** Statt nur „Fallback" steht am
Eintrag der Grund — „Ollama hat nicht geantwortet", „Ende gekürzt (Wiederholung)",
„Formel-Platzhalter verloren", „Sinnumkehr: 1 Zahl fehlt". Jeder Eintrag merkt sich
außerdem, welches Profil galt und in welchem Fenster du diktiert hast; Wörter, die
Fleech am Ende des Rohtranskripts verworfen hat, werden mitgespeichert und im
Detail-Dialog gezeigt — ein Fehlgriff der Filter lässt sich so zurückholen. In der
Verlaufsliste tragen solche Diktate einen kleinen ambernen Punkt. Die Insights-Karte
„Verarbeitung" zeigt unter der Fallback-Quote, woran es lag („Rückfälle: 2× Ollama ·
1× Sinnumkehr"). Bestehende Verläufe bleiben vollständig erhalten. Das Protokoll
(`fleech.log`) trägt jetzt bei jeder Zeile das Datum und wächst nicht mehr endlos —
ab 20 MB wird rotiert, drei ältere Stände bleiben.

**Hotkeys, die ankommen.** Diktier-Hotkeys auf Makro- oder G-Tasten (Corsair iCUE,
Logitech G HUB) funktionieren jetzt zuverlässig: Ein verschlucktes Loslassen macht die
Taste nicht mehr wirkungslos. Wer eine Taste länger hält, löst sie nicht mehr
versehentlich zweimal aus — Pause, KI-Prompting und Profilwechsel richten sich nach
der in Windows eingestellten Tastenwiederholung. Während „Rohtext einsetzen" läuft,
reagieren die übrigen Hotkeys weiter (bisher war die Tastatur bei langen Diktaten
bis zu 20 Sekunden für Fleech blockiert), und die Backspaces landen nicht mehr im
falschen Dokument, wenn du das Fenster gewechselt hast; der Hinweis dazu sagt, was
Fleech erkennen kann und was nicht.

**Weniger stille Fehler.** Schlägt der Mikrofon-Start fehl oder fehlt der
Lizenzschlüssel, bleibt die Fehlermeldung stehen statt von „nichts erkannt"
überschrieben zu werden. Fehlt das gewählte Mikrofon, sagt Fleech es in der Pille
und nennt das Gerät, über das jetzt aufgenommen wird. Läuft die lokale KI gar nicht,
sagt Fleech einmal pro Sitzung, wo die Einrichtung steht. Ein kopiertes Bild bleibt
nach einem Diktat in der Zwischenablage — zurückgeschrieben wird nur Text, der
vorher auch Text war. Beim Beenden werden Discord, Spotify & Co. wieder laut gestellt,
auch mitten in einer Aufnahme; die Lautstärke fremder Apps sinkt nicht mehr von
Diktat zu Diktat weiter ab. Im Anstupsen-Modus gibt es keinen doppelten Stoppton
mehr, wenn Sprechpause und Tastendruck zusammentreffen. Ein gelöschtes Profil fasst
Einstellungen und Pille nicht mehr mitten in der Verarbeitung an.

**Insights, die stimmen.** „Als Regel übernehmen" schlägt nur noch echte
Erkennungsfehler vor — keine Grammatik („kann → können"), Formeln oder
Anführungszeichen mehr, die künftig jedes Diktat verfälscht hätten; die Zeile sagt,
was die Regel tut. „Verarbeitung" zeigt, wie schnell die Hälfte bzw. neun von zehn
Diktaten wirklich fertig waren, statt eines Mittelwerts, den Kaltstarts verzerren.
Der Buchvergleich bezieht sich auf alle je diktierten Wörter und wechselt nicht mehr
bei jedem Diktat den Titel. „Deine Muster" schweigt bei zu kurzen Zeiträumen statt
Banales zu verkünden und vergleicht Tageszeiten pro Stunde. „Korrekturen" zählt nur
echte Bereinigungen; umformulierte Diktate stehen als eigene Zeile. Große Zahlen
haben einen Tausenderpunkt. Die Karte „Befehle" ist als Zeile in „Deine Muster"
gewandert — zeitraum-richtig, sie zeigte bisher immer den ganzen Verlauf.

---

## 5.10.3 — 2026-08-18

*Nicht einzeln veröffentlicht.* Erste Runde aus der Tiefenanalyse vom 17./18. August:
alles, was die App etwas anderes anzeigen ließ, als sie tat — und der Schutz der
Einstellungsdatei.

**Einstellungen gehen nicht mehr verloren.** Speichert Fleech im selben Moment aus
zwei Richtungen (etwa am Ende eines Diktats und bei einem Klick in den Einstellungen),
konnte bisher eine unlesbare `settings.json` entstehen. Und stand die Datei nach einem
Unfall plötzlich auf Werkseinstellung — Lizenz weg, Hotkey wieder F9 —, ließ Fleech es
dabei. Jetzt holt es beim Start die letzte gute Fassung zurück und legt die
zurückgesetzte Datei als `settings.json.zurueckgesetzt` daneben; einzelne Werte, die
man selbst zurückgesetzt hat, bleiben unangetastet. Eine kaputte Datei wird nicht mehr
zur Sicherung gemacht. Beim Start steht im Protokoll, wie viele Profile,
App-Zuordnungen, Schnellwechsel-Einträge und Wörterbuchzeilen geladen wurden und ob
eine Lizenz da ist — ein Verlust fällt sofort auf.

**Das Profil „Stichpunkte" funktioniert jetzt auch beim Diktieren.** Bisher kam trotz
gewähltem Profil Fließtext heraus — das Format erreichte die Verarbeitung nie; nur die
gesprochene Ansage „… als Stichpunkte" ging.

**„Diktat direkt abschicken" wirkt jetzt in den Profilen „KI-Prompt" und
„Stichpunkte"** — genau dort, wofür der Haken gedacht ist. Beim Format „E-Mail" greift
er weiterhin bewusst nicht.

**Die Formel-Erkennung zeigt, was sie tut.** Nach einer frischen Installation stand
sie auf „Automatisch", obwohl keine Formeln erkannt wurden. Wer Formeln will, schaltet
sie jetzt sichtbar unter Einstellungen → Ausgabe ein — und bekommt sie dann auch. Das
Ausgabeformat „Formeln" ist aus der Profilauswahl verschwunden (es hat nie etwas
bewirkt); das Profil „Mathe" bleibt mit Name, Eingriffsgrad und Farbe.

**Der Schnellwechsel überspringt das Standardprofil.** Ein Klick zu weit auf den
Pillen-Punkt oder den Profil-Hotkey landete bisher auf „Standard" — und das legte
unbemerkt und dauerhaft alle App-Zuordnungen still, ohne anders auszusehen als
„App-Standard". Letzteres leistet dasselbe und lässt die Zuordnung zu. Passen zwei
Titelregeln auf ein Fenster, gewinnt jetzt die genauere.

**Uhrzeiten kosten keinen Fehlversuch mehr.** Machte Fleech aus „18.50 Uhr" ein
„18:50 Uhr", galt das als verlorene Zahl — in genau diesen Diktaten landete der
unbereinigte Text im Feld, mit Fehlerton. Ebenso dürfen Datumsangaben wie „15.07."
zu „15. Juli" werden.

**„Strong" glättet weiter stark, prüft aber wieder auf verschluckte Zahlen und
Verneinungen** — wichtig für „Geschäftlich" und „E-Mail", wo Termine und Beträge stehen.

**Ehrlichere Rückmeldung.** Antwortet die KI leer, meldet Fleech das als Rückfall
(Warnton, amberner Hinweis) statt eines grünen Hakens. Verliert die KI bei Formel plus
Textbaustein die Formel, fällt Fleech sichtbar auf den Rohtext zurück, statt still ein
Loch einzufügen. Ein Schlusssatz mit Formel wird nicht mehr als „erfunden"
abgeschnitten. Verhörte Endlosschleifen mitten im Text („um, um, um, um, um",
„G-G-G-G-G") werden auf eine Nennung gekürzt und in der Pille gemeldet; dreifache
Betonung wie „nein, nein, nein" bleibt.

**Gesprochene Zeichen:** „Raute", „Unterstrich" und „Schrägstrich" bleiben normale
Wörter — aus „zeichne eine Raute darunter" wird kein „#darunter" mehr; folgt ein
gewöhnliches Wort, bleibt das Leerzeichen stehen.

**Mikrofonwechsel im Betrieb** wird sofort neu bewertet — die Warnung vor
Loopback-/Mix-Geräten folgt dem neuen Gerät statt bis zum Neustart am alten zu hängen.

**Texte, die jetzt stimmen.** Der Hinweis am Diktat-Hotkey sagt, dass Esc/Entf/
Backspace die Bindung *löschen*; der Aufnahme-Dialog hat einen „Abbrechen"-Knopf.
Das „?" neben jeder Auswahlliste erklärt alle Optionen, nicht nur die gewählte — man
muss „Anstupsen" nicht mehr einschalten, um zu erfahren, was es ist. Die Einführung
erklärt Formeln richtig (kein toter Hotkey) und bietet „Anstupsen" als dritten
Bedienmodus an. Warmhaltung nennt ~3,5 GB statt ~8 GB. „Adaptive Geschwindigkeit" und
die Insights-Statistik behaupten kein zweites Modell mehr. Click-Through warnt, dass
dabei auch die Knöpfe der Pille unbedienbar werden. Die Freihand-Einstellungen sind
vollständig ausgegraut, solange der Modus stillgelegt ist. „Auto-Hide nach" erscheint
nur bei „Automatisch ausblenden". Das Safe-Word-Feld zeigt, welches Wort gilt. Der
Hinweis am KI-Prompting-Hotkey nennt den richtigen Weg (Profil „KI-Prompt"). Das Tray
sagt nicht mehr „Freihand: an". „Debug-Logging" tut ab dem nächsten Start endlich
etwas. Die Weitergabe-Dokumentation verspricht keine Offline-Nutzung ohne
Update-Prüfung mehr und nennt realistische Wartezeiten.

**Aufgeräumt:** Einstellungen zu einem Formel-Modus, den es seit Version 3 nicht mehr
gibt (Mathe-Hotkeys, „Mathe-Umschalt"), sind entfallen; bestehende
Einstellungsdateien laden unverändert.

---

## 5.10.2 — 2026-08-17

*Nicht einzeln veröffentlicht.*

**Der Profil-Punkt an der Pille wechselt das Profil nur noch während einer
laufenden Aufnahme.** Vorher ging das jederzeit — die Pille liegt am
Bildschirmrand, und ein beiläufiger Klick stellte still auf ein anderes Profil
um. Gemerkt hat man es erst beim nächsten Diktat, wenn plötzlich eine E-Mail
herauskam statt normalem Text.

Der Punkt bleibt außerhalb der Aufnahme sichtbar und zeigt weiter in seiner Farbe,
welches Profil gerade gilt — er nimmt nur keine Klicks mehr an. Wer vorher wählen
will, nimmt den Profil-Hotkey (tippen = nächstes Profil, halten = Auswahlliste)
oder die Profilseite.

---

## 5.10.1 — 2026-08-05

*Nicht einzeln veröffentlicht.*

**Fleech fragt beim Erststart, ob es die Diktate aufheben soll.** Bisher war der
Verlauf einfach an, und der Schalter lag versteckt unter Einstellungen →
Allgemein. Er bleibt standardmäßig an — Startseite und Auswertungen leben davon —,
aber jetzt ist es eine Entscheidung statt einer Voreinstellung, die man nie zu
Gesicht bekommt. Der Anlass war ein externes Gutachten: Gespeichert wird der
vollständige Wortlaut, unverschlüsselt; wer Vertrauliches diktiert, sollte das
wissen.

**Freihand ist vorerst abgeschaltet.** Der Modus, bei dem Fleech dauerhaft auf ein
Startwort lauscht, lässt sich nicht mehr einschalten. Er ist nicht entfernt, nur
stillgelegt — in den Einstellungen steht, warum: Ein offenes Mikrofon per Sprache
auszulösen war in einem Raum mit Nebengeräuschen nicht zuverlässig zu bekommen,
und jeder Fehlstart tippt Text in das Fenster, in dem du gerade arbeitest.

Was Freihand eigentlich können sollte, kann der Bedienmodus **Anstupsen**: einmal
drücken, reden, es hört von selbst auf. Auslösen kann dort nur, wer die Taste
drückt.

## 5.10.0 — 2026-08-05

Die erste Veröffentlichung seit 5.5. Alles aus 5.6 bis 5.9 ist enthalten; unten
stehen die Punkte, die du im Alltag merkst.

**Diktieren, ohne am Ende wieder zur Tastatur zu greifen.** Der neue Bedienmodus
**Anstupsen** (Einstellungen → Aufnahme → Bedienmodus): einmal drücken, reden,
aufhören — die Aufnahme endet von selbst. Eine Denkpause schneidet nichts ab, und
wer zwischendurch pausiert, um mit jemandem zu sprechen, verliert nichts. Ein
zweiter Druck beendet trotzdem sofort.

**Das Ausgabeformat lässt sich am Ende ansagen.** Diktieren und zum Schluss „…
als Stichpunkte" sagen. Ebenso „als E-Mail", „als KI-Prompt" oder „als Diktat".
Das gilt für dieses eine Diktat und übersteuert das Profil.

**Stichpunkte verdichten jetzt wirklich.** Bisher wurde jeder Satz einzeln
umgeschrieben — an echten Diktaten gemessen sind die Ergebnisse jetzt 29 bis 65
Prozent kürzer, ohne dass ein genannter Punkt verlorenginge.

**Wörterbuch-Einträge lassen sich einsprechen.** Cursor in die Zeile, „Eintrag
einsprechen …", Wort sagen. Fleech zeigt, was ankommt — und bietet die passende
Ersetzungsregel gleich zum Eintragen an, wenn etwas anderes verstanden wurde.

**Freihand hört deutlich besser — und lässt sich bedienen.** Drei Dinge waren
kaputt: Die Startwort-Prüfung blockierte den Mikrofonstrom (die Hälfte des
Gesprochenen kam nicht an), die Aufnahme war oft schon vorbei, bevor man
reagieren konnte, und die Knöpfe der Pille taten beim Freihand-Diktat nichts.
Alles behoben. Dazu **mehrere Startwörter**: Wort eintippen, Enter, es steht als
Zeile darunter — Fleech startet bei jedem davon.

Trotzdem ehrlich gesagt: Ein dauerhaft offenes Mikrofon in einem Raum mit
Nebengeräuschen bleibt schwierig. Wenn es dir um das automatische Ende geht, ist
„Anstupsen" die zuverlässigere Wahl.

**Einheitliche Oberfläche.** Auf der Seite „Apps" standen die Karten weiter vom
Rand und die Überschrift war größer als anderswo; beim Umschalten sprang das
Layout. Das ist angeglichen.

**Unter der Haube.** Die größten Quelldateien wurden nach Themen aufgeteilt (eine
davon hatte 1979 Zeilen in einem Stück). Für dich ändert sich dabei nichts — es
sorgt dafür, dass Änderungen an einer Ecke seltener eine andere umstoßen.

## 5.9.1 — 2026-08-05

*Nicht einzeln veröffentlicht.*

**Für dich ändert sich nichts — das ist der Punkt.** Diese Version räumt nur den
Code auf: Die größten Dateien waren über die Zeit zu Sammelbecken geworden (eine
davon mit 1979 Zeilen und 89 Funktionen in einem Stück). Sie sind jetzt nach
Themen aufgeteilt. Keine Funktion ist dazugekommen, keine verschwunden, keine
Einstellung hat sich verschoben.

Der Nutzen ist mittelbar, aber real: Änderungen an einer Ecke von Fleech können
seltener eine andere Ecke umstoßen, und neue Sachen sind schneller gebaut. Damit
das so bleibt, wacht die Testsuite jetzt auch über die Aufteilung selbst — wenn
eine Datei wieder zum Sammelbecken wird, schlägt sie Alarm.

---

## 5.9.0 — 2026-08-04

**Mehrere Startwörter.** Unter Einstellungen → Aufnahme tippst du ein Wort ein,
drückst Enter, und es steht als Zeile darunter — mit einem ✕ zum Entfernen.
Fleech startet bei jedem davon.

Der Grund: Welches Wort die eigene Aussprache zuverlässig trifft, lässt sich
nicht vorhersagen. Mit zwei oder drei Kandidaten nebeneinander entfällt das
Herumprobieren mit einem einzigen. Alle eingetragenen Wörter werden der Erkennung
vorgesagt, nicht nur das erste.

**Die Pille war zu früh wieder weg.** Sagtest du das Startwort und wolltest dann
abbrechen, war die Aufnahme oft schon vorbei — im Protokoll immer nach exakt zwei
Sekunden. Ursache war eine Messgrenze: Die Spracherkennung braucht knapp eine
Sekunde Ton, bevor sie überhaupt sagen kann, ob jemand spricht. In dieser Zeit
lief die Stille-Uhr gegen eine Antwort, die noch gar nicht vorliegen konnte.
Jetzt startet sie erst, wenn wirklich genug Ton da ist — du hast Zeit,
loszusprechen oder abzubrechen.

**Alle Seiten haben jetzt dieselben Abstände.** Auf „Apps" standen die Karten
weiter vom Rand und die Überschrift war größer als auf Home, Insights und
Profile; beim Umschalten sprang dadurch das Layout. Die Maße stehen jetzt an
einer Stelle, statt viermal einzeln im Code.

## 5.8.3 — 2026-08-04

*Nicht einzeln veröffentlicht.*

**Die Pille reagiert jetzt auch beim Freihand-Diktat.** Abbrechen, Fertig und
Pause taten dort schlicht nichts: Alle drei Knöpfe waren an den Hotkey-Weg
gebunden, und der läuft beim Freihand-Diktat gar nicht. Die Knöpfe sahen dabei
ganz normal aus — man klickte und wartete auf etwas, das nie kam.

Besonders unangenehm war das in Räumen mit Hintergrundgeräuschen: Läuft dort ein
Video oder unterhält sich jemand, hört Fleech durchgehend Sprache und wartet
weiter auf eine Sprechpause, die nicht kommt. Ohne funktionierenden Knopf saß man
in der Aufnahme fest. Genau das ist behoben — und als zweite Sicherung endet ein
Freihand-Diktat jetzt spätestens nach zwei Minuten von selbst.

Die Pause hält dabei auch die Uhr an: Wer mitten im Diktat kurz mit jemandem
spricht, verliert das Gesagte nicht.

## 5.8.2 — 2026-08-04

*Nicht einzeln veröffentlicht.*

**Fehlersuche für das Startwort.** Unter Einstellungen → Aufnahme → Fehlersuche
lässt sich einschalten, dass Fleech die geprüften Startwort-Fenster als
Tondateien aufhebt (zwei Sekunden je Prüfung, höchstens 60 Stück, in
`%APPDATA%\Fleech\freihand-diagnose`). Die Dateinamen sagen, was verstanden wurde
und ob es als Treffer zählte.

Der Anlass: Das Startwort wird beim Einsprech-Test zuverlässig erkannt, im
laufenden Betrieb aber nicht — und alles, was sich ohne echte Aufnahme
vergleichen liess, sah identisch aus. Ohne zu hören, was tatsächlich ankommt,
bleibt jede weitere Erklärung geraten.

**Standardmäßig aus, und das bleibt so.** Hier wird Audio gespeichert — genau
das, was Freihand sonst ausdrücklich nicht tut. Nach der Fehlersuche wieder
ausschalten.

## 5.8.1 — 2026-08-04

*Nicht einzeln veröffentlicht.*

**Fleech startet wieder.** 5.8.0 brach beim Start ab — die Uhr für den neuen
Anstupsen-Modus wurde falsch angelegt. Wer dabei Tasten drückte, bekam
merkwürdige Eingaben zu sehen: Die Tastenerkennung lief zu diesem Zeitpunkt
schon und blieb in dem halb gestarteten Programm hängen. Beides ist behoben — ein
abgebrochener Start räumt die Tastenerkennung jetzt sauber ab.

**Startfehler stehen jetzt im Protokoll.** Bisher gingen sie nur in ein Fenster,
das bei der fertigen Anwendung niemand sieht; im Protokoll sah ein abgestürzter
Start wie ein gelungener aus. Es gibt jetzt auch eine Zeile, die den geglückten
Start ausdrücklich bestätigt.

## 5.8.0 — 2026-08-04

**Neuer Bedienmodus „Anstupsen": einmal drücken, reden, fertig.** Die Aufnahme
endet von selbst, sobald du aufhörst zu sprechen — du musst am Ende nicht wieder
zur Tastatur greifen. Ein zweiter Druck beendet trotzdem sofort, falls es mal
schneller gehen soll.

Zu finden unter Einstellungen → Aufnahme → Bedienmodus, neben „Hold-to-talk" und
„Toggle". Wie lange eine Sprechpause dauern darf, stellst du direkt darunter ein
(Vorgabe: 2 Sekunden); der Regler erscheint nur in diesem Modus.

Das ist der Weg, den der Freihand-Modus eigentlich gemeint hat. Der Wunsch
dahinter war nie, mit der Stimme zu *starten* — sondern am Ende nicht wieder
anfassen zu müssen. Und nur diese Hälfte lässt sich zuverlässig bauen: Ein
dauerhaft offenes Mikrofon in einem Raum, in dem auch mal ein Video läuft oder
jemand spricht, löst früher oder später falsch aus, und jeder Fehlstart tippt
Text in das Fenster, in dem du gerade arbeitest. Beim Anstupsen kann nur
auslösen, wer die Taste drückt.

Eine Denkpause schneidet nichts ab: Sobald du weiterredest, läuft die Uhr neu an.
Und wenn du die Aufnahme pausierst, um mit jemandem zu sprechen, ruht auch die
Automatik.

**Freihand bleibt vorhanden, aber nicht mehr empfohlen.** Wer es nutzt, kann es
weiter nutzen; in den Einstellungen steht jetzt dabei, was der zuverlässigere Weg
ist.

## 5.7.0 — 2026-08-04

**Freihand hört jetzt so gut wie das Diktat.** Bisher erkannte Fleech dasselbe
Wort im normalen Diktat mühelos und überhörte es beim Lauschen ständig. Der Grund
lag nicht am Startwort, sondern daran, dass die Startwort-Prüfung den Mikrofonstrom
blockierte: Während sie rechnete, verwarf Windows die hereinkommende Aufnahme.
Gemessen kam nur noch die **Hälfte** des Gesprochenen an — die Prüfung bekam
Bruchstücke und riet daraus „Ich bin hier.", „Wirksam.", „Vielen Dank."

Die Prüfung läuft jetzt neben der Aufnahme statt in ihr; es geht nichts mehr
verloren. Und sie nutzt dasselbe Modell, das ohnehin für deine Diktate geladen
ist: genauer als das kleine Modell von vorher, mit 140 statt 440 Millisekunden
schneller, und ohne zusätzlichen Grafikspeicher.

Wer bei der Genauigkeit nichts eingestellt hatte, wird automatisch umgestellt.
Unter Einstellungen → Aufnahme → Genauigkeit stehen die sparsamen Varianten
weiterhin bereit — für Rechner ohne brauchbare Grafikkarte.

**Startwort einsprechen.** Unter Einstellungen → Aufnahme steht jetzt „Startwort
einsprechen …". Wort sagen, und Fleech zeigt, was ankommt und ob Freihand darauf
anspringen würde. Ob ein Startwort taugt, hängt an der eigenen Aussprache — das
lässt sich nicht vorhersagen, nur ausprobieren.

Zur Wahl des Wortes: Kunstwörter, die wie ein Alltagswort klingen, sind eine
schlechte Idee. „Fleech" etwa kommt als „Fleisch" an und würde beim Kochrezept
auslösen. „Kimono" bleibt die sichere Wahl.

## 5.6.0 — 2026-08-04

**Stichpunkte verdichten jetzt wirklich.** Bisher wurde jeder Satz einzeln
umgeschrieben: Aus „Manche Profile haben einen farbigen Punkt und andere nicht"
wurde derselbe Satz mit Strich davor — eine Feststellung statt einer Aufgabe, und
Versprecher wanderten mit. Jetzt steht dort „Farbigen Punkt für alle Profile,
Farbe auswählbar".

An echten Diktaten gemessen, die dem Modell nicht als Beispiel vorlagen: 29 bis
65 Prozent kürzer, ohne dass ein genannter Punkt verlorenging. Die oberste Regel
bleibt unangetastet — es wird nichts weggelassen, nur die Art zu sprechen.

**Wörterbuch-Einträge lassen sich einsprechen.** Unter Einstellungen →
Textersetzung gibt es „Eintrag einsprechen …": Cursor in die Zeile, Knopf drücken,
Wort einmal sagen. Fleech zeigt, was ankommt — und wenn etwas anderes verstanden
wurde, bietet es die passende Ersetzungsregel gleich zum Eintragen an.

Bisher trug man ein Wort ein und merkte erst mitten im nächsten Diktat, ob es
etwas gebracht hat. Der Test läuft über dieselbe Erkennung wie ein echtes Diktat,
mit demselben Wörterbuch-Priming — sonst würde er etwas anderes messen als den
Alltag.

**Das Ausgabeformat lässt sich am Ende ansagen.** Diktieren und zum Schluss
„… als Stichpunkte" sagen — der Zusatz wird erkannt, aus dem Text entfernt und das
Diktat entsprechend verarbeitet. Ebenso „als E-Mail", „als KI-Prompt" oder „als
Diktat" für ausdrücklich normal. Das übersteuert das Profil für genau dieses eine
Diktat.

Erkannt wird nur am **Satzende** und nur mit Einleitung („als", „bitte als",
„mach das als"). „Ich schicke das als E-Mail raus" bleibt deshalb Diktat — ein
Wort wie „als" kommt im Sprechen zu oft vor, um es überall als Befehl zu deuten.

**Behoben: Eine Whisper-Schleife kam komplett ins Textfeld.** Der Filter gegen
Wiederholungen prüft das Textende — stand dort ein angebrochenes Wort („… don't,
don't, don"), fand er keine Wiederholung und ließ alle 75 Wörter durch. Ein
einziges halbes Wort setzte die Schutzschicht außer Kraft.

**Behoben: Sicherheitsregel für die umformulierenden Formate.** Der Schutz gegen
„Modell führt das Diktat als Anweisung aus" wurde nur bei der normalen
Bereinigung erzwungen. Stichpunkte und E-Mail formulieren den ganzen Text um —
dort wäre eine im Diktat versteckte Anweisung genauso wirksam.

---

## 5.5.0 — 2026-08-03

**Jedes Profil hat jetzt eine Farbe — und du wählst sie aus.** Bisher trugen nur
vier Profile einen farbigen Punkt (E-Mail, KI-Prompt, Formeln, Stichpunkte); bei
allen anderen blieb die Stelle davor leer, als würde etwas fehlen. Jetzt hat
jedes Profil seinen Punkt, und auf der Profilseite steht unter dem Ausgabeformat
eine Reihe mit acht Farben zum Antippen.

Wer nie eine Farbe wählt, merkt vom Umbau nichts: Die vier bekannten Profile
sehen aus wie vorher, alle übrigen bekommen eine feste Farbe aus ihrem Namen —
dieselbe bei jedem Start, auch wenn du die Liste umsortierst.

**Die Farbe ist beim Diktieren sichtbar.** Der runde Knopf links an der Pille —
der, mit dem du das Profil durchschaltest — trägt jetzt einen Ring in der Farbe
des aktiven Profils. Damit siehst du im Vorbeischauen, welches Profil gerade
greift, ohne etwas anzuklicken.

Die übrigen Anzeigen am selben Knopf bleiben unterscheidbar: Ein **gefüllter**
Punkt heißt weiterhin „KI-Prompting ist eingerastet" (jetzt in der Profilfarbe
statt immer amber), der zweite, weitere Ring bleibt türkis für „Freihand hört
mit", und der kleine Punkt unten rechts weiterhin für den gemerkten Diktat-Kontext.
Sind Profile global ausgeschaltet, bleibt der Ring grau wie bisher.

**Freihand startet jetzt auch mit einem USB-Mikrofon.** Windows meldet dasselbe
Mikrofon einmal je Audio-Schnittstelle — ein Scarlett Solo taucht viermal auf.
Freihand konnte sich nicht entscheiden und startete gar nicht: Der Schalter stand
auf an, aber es wurde nie zugehört, unabhängig vom gewählten Startwort. Der
Hotkey-Weg war davon nie betroffen, deshalb fiel es nicht sofort auf.

Zwei Dinge geändert: Freihand wählt das Gerät jetzt genauso aus wie die normale
Aufnahme, und wenn das Wunschmikrofon nicht geht, wird das Standardgerät
genommen, statt aufzugeben. **Und falls es doch einmal scheitert, siehst du es
jetzt** — vorher stand das nur im Protokoll, während der Schalter weiter auf „an"
stand.

**Das Startwort wird auch erkannt, wenn du gleich weitersprichst.** Das kleine
Prüfmodell versteht „Kimono" zuverlässig, wenn das Wort allein steht — sagt man
„Kimono, schreib das bitte auf", macht es daraus „Kimunno". Der Vergleich war
exakt, also passierte nichts. Er verzeiht jetzt kleine Hörfehler.

Wortgrenzen gelten unverändert: „Kimonos" und „Kimonoartiges" lösen weiterhin
nicht aus, ebenso wenig ähnlich klingende Alltagswörter wie „Kino", „Mono",
„Simon" oder „Domino" — die Toleranz ist an echten Modellausgaben kalibriert.

**Und Fleech schreibt jetzt mit, was es gehört hat.** Im Protokoll steht bei
jeder Prüfung, welches Wort verstanden wurde und ob es als Startwort zählte.
Ohne das war nicht feststellbar, warum nichts passiert — man verdächtigt sein
Startwort und probiert andere aus, obwohl es daran gar nicht liegt.

**Das Startwort wird jetzt auch dann erkannt, wenn es undeutlich ankommt.** An
einer echten Stimme über ein echtes Mikrofon gemessen: Aus „Kimono" macht das
Prüfmodell je nach Aussprache „Kimu", „Kimun", „Kimo no" oder „Gimo" — es
schneidet das Wort ab oder zerreißt es. Der Vergleich erkennt beide Fälle jetzt.
Ähnlich klingende Alltagswörter bleiben draußen: „Kino", „Mono", „Simon",
„Simone", „Domino", „Kimme" und „Kimchi" lösen weiterhin nicht aus.

Zusätzlich bekommt das Prüfmodell dein Startwort vorab gesagt — derselbe
Kniff, den Fleech beim Wörterbuch nutzt. Das trifft besser **und** ist schneller
(350 → 226 ms je Prüfung).

**Kein Kauderwelsch mehr, wenn nach dem Startwort nichts kommt.** Sagt man das
Startwort und wartet erst einmal ab, lief die Aufnahme bisher in die Stille — und
aus zwei Sekunden Mikrofonrauschen machte die Erkennung ein „G-G-G-G-G-…", das
im Textfeld landete. Solche Aufnahmen werden jetzt verworfen. Und falls doch
einmal so ein Muster durchkommt, fängt es eine neue Prüfung ab: Sie erkennt
Wiederholungen **innerhalb** eines Wortes, was bisher niemand geprüft hat.

**Das Diktat kommt jetzt vollständig an.** Der schwerste Fehler steckte tief: Die
Audio-Bibliothek reicht bei jeder Lieferung denselben Speicher herein und
überschreibt ihn danach — Freihand merkte sich nur einen Verweis darauf. Am Ende
enthielt die „Aufnahme" deshalb vielfach denselben letzten Schnipsel. Weil die
Aufnahme bei Stille endet, war dieser Schnipsel still: Das Diktat kam leer an.
Und wo doch etwas ankam, ergab derselbe Schnipsel aneinandergereiht einen
gleichförmigen Ton — daher das „T-T-T-T-…" und „G-G-G-G-…" im Textfeld.

**Die Aufnahme läuft, solange du redest.** Bisher war nach exakt zwei Sekunden
Schluss, egal wie lange du sprachst. Die Sprech-Erkennung beurteilte nur
Fünftelsekunden-Häppchen, und darauf meldet sie nie Sprache — gemessen in 0 % der
Fälle, gegenüber 100 % bei einer Sekunde. Die Stille-Uhr lief also durch, obwohl
geredet wurde.

**Die Pille zeigt beim Freihand-Diktat wieder den Pegel** und die Live-Vorschau
läuft auch dort. Beides hing bisher am Tasten-Weg; beim Freihand-Diktat blieb die
Pille tot, und man wusste bis zum Schluss nicht, ob überhaupt etwas ankommt.

**Genauigkeit einstellbar** (Einstellungen → Aufnahme): Schnell, **Ausgewogen**
(neue Vorgabe) oder Genau. Das bisherige schnelle Modell verstand „Kimono" je
nach Aussprache als „Kimu" oder „Gimo" und „Apfel" als „Achtung"; die
ausgewogene Stufe trifft beides.

> **Tipp zum Startwort:** Mehrsilbig und im Alltag selten. Kurze Allerweltswörter
> funktionieren schlecht — „Apfel" versteht das kleine Modell je nach Aussprache
> als „Achtung", „Abflö" oder „Applaus".

---

## 5.4.0 — 2026-08-03

**Englisch diktieren.** Pro Profil einstellbar — Deutsch, Englisch oder
automatisch erkennen. Die Erkennung, die Schutzfilter und die Bereinigung
richten sich danach.

**Der Filter gegen Wortsalat kann jetzt beide Sprachen.** Zwei seiner vier
Merkmale waren sprachgebunden: englische Füllwörter und fehlende deutsche. Bei
einem englischen Diktat waren beide immer gesetzt — und zwei Merkmale bedeuten
Schnitt. Jedes englische Diktat wäre am Ende gekürzt worden. Die Merkmale
spiegeln sich jetzt mit der Sprache; der Filter bleibt gleich streng, er misst
nur gegen die richtige Erwartung.

**Mischdiktate bleiben ganz.** Deutsche Sätze mit englischen Fachbegriffen
(„der MCP-Server", „das Deployment") laufen unverändert durch — es zählt der
Anteil, nicht das einzelne Wort. Umgekehrt bleiben in englischen Diktaten
deutsche Begriffe stehen.

**Eigener Prompt für Englisch.** Gemessen: Mit dem deutschen Prompt hat das
Modell englische Diktate ins Deutsche *übersetzt*, und ein bloßer Hinweis
(„answer in English") änderte daran nichts. Es gibt deshalb `prompts/cleanup-en.md`
— mit denselben Regeln, allen voran der wichtigsten: nah am Gesprochenen bleiben.

Die Oberfläche bleibt auf Deutsch. Sie zu übersetzen würde die Pflege jeder
künftigen Zeile verdoppeln, ohne dass ein Diktat dadurch besser wird.

## 5.3.0 — 2026-08-03

**Diktieren ohne Taste.** Startwort sagen, sprechen, aufhören — der Text steht da.
Kein Klick, kein Tastendruck. Der Hotkey bleibt unverändert; Freihand kommt
dazu und ist **standardmäßig aus**.

Einzustellen unter *Einstellungen → Aufnahme*: Startwort (Vorgabe „Kimono" —
mehrsilbig und im Alltag selten, sonst löst es im Gespräch ständig aus),
Abbruchwort, wie lange Stille ein Diktat beendet (1–4 s) und in welchen
Programmen gar nicht gelauscht wird. Für Spiele und Besprechungen ist Letzteres
wichtig: Dort ist Sprache im Raum die Regel.

Im Infobereich steht ein **Schnellschalter** — wer merkt, dass er gerade nicht
mitgehört haben will, beendet es mit einem Griff. Solange gelauscht wird, trägt
der Punkt an der Pille einen ruhigen Ring: Ob mitgehört wird, muss man sehen
können.

**Was dabei mit dem Ton passiert:** Ein sparsamer Sprach-Erkenner läuft mit und
prüft nur, *ob überhaupt jemand spricht* — gemessene Dauerlast rund 1 % eines
Prozessorkerns. Erst wenn das anschlägt, sieht ein kleines Modell nach, ob das
Startwort gefallen ist. Gespeichert wird nichts: Im Speicher liegen immer nur die
letzten zwei Sekunden, und die überschreiben sich fortlaufend. Gesammelt wird
erst ab dem erkannten Startwort.

## 5.2.0 — 2026-08-03

**Der Text steht sofort da.** Die Erkennung ist nach knapp einer Sekunde durch,
die Bereinigung braucht danach noch rund vier. In dieser Lücke stand bisher
nichts — jetzt erscheint das Rohtranskript sofort in der Pille und wird später
durch die fertige Fassung ersetzt. Man liest bereits, während das Modell arbeitet.

**Die Statuszeile sagt, was gerade passiert** — „Bereinige …", „E-Mail wird
formuliert …", „Füge ein …". Die Meldungen hängen an den echten Schritten, nicht
an einem geschätzten Fortschrittsbalken. Steht schon ein Rohtext, tritt die Stufe
darunter, statt ihn zu verdrängen.

**Falsches Profil erwischt? Rechtsklick genügt.** Im Verlauf öffnet ein
Rechtsklick ein Menü: „Neu bereinigen als …" schickt das gespeicherte
**Rohtranskript** noch einmal durch die Pipeline — als E-Mail, als Stichpunkte,
als KI-Prompt. Kein neues Diktat nötig. Dazu Text und Rohtext kopieren.

Das Ergebnis landet in der **Zwischenablage**, nicht im ursprünglichen Textfeld:
Wer im Verlauf rechtsklickt, steht im Fleech-Fenster — blind ins zuletzt benutzte
Feld zu schreiben ist genau die Fehlerklasse, aus der die Cursor-Regeln stammen.

**Die Prompts sind offen.** Auf der Profilseite zeigt „Prompt ansehen …", welche
Anweisung das Sprachmodell bei diesem Ausgabeformat bekommt — und lässt sie
ändern. Eigene Fassungen liegen neben dem Programm und überleben Updates; der
Werkszustand bleibt daneben und ist per Knopf wieder herstellbar. Die
Sicherheitsregel zu den Text-Markern ergänzt Fleech notfalls selbst; sie lässt
sich nicht wegkürzen.

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
