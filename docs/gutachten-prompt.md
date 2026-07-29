# Prompt für ein externes Gutachten (Deep Research)

Zusammen mit `docs/fleech-briefing.html` an ein Recherche-/Analysesystem geben.
Bewusst richtungsoffen gehalten: Er beschreibt den Gegenstand und den Anspruch an
die Antwort, aber **nicht**, was gefunden werden soll.

---

Du bist ein unabhängiger Gutachter. Ich lege dir ein Softwareprojekt vor und
möchte deine fachliche Einschätzung — ergebnisoffen. Ich habe bewusst keine
Vermutung formuliert, was du finden sollst; die Richtung entwickelst du selbst
aus dem, was du siehst.

**Der Gegenstand**

„Fleech" ist ein Diktier-Werkzeug für Windows und Linux, gebaut von einer Person
für den eigenen täglichen Gebrauch. Man hält eine Taste, spricht, lässt los — der
bereinigte Text erscheint in dem Eingabefeld, in dem der Cursor gerade steht.
Spracherkennung und Sprachmodell laufen vollständig auf dem eigenen Rechner; es
gibt im gesamten Verarbeitungsweg keinen Netzwerkaufruf. Python mit Qt-Oberfläche,
rund 23.000 Zeilen inklusive Tests, seit etwa einem Jahr in echtem Einsatz mit
inzwischen knapp 1.000 aufgezeichneten Diktaten.

Das beiliegende Briefing (eine eigenständige HTML-Datei) enthält den vollständigen
Verarbeitungsweg in neun Phasen mit 38 Einzelschritten, Bildschirmfotos der
Oberfläche, sämtliche Einstellungsmöglichkeiten, die Architektur, echte
Betriebskennzahlen und eine offene Auflistung bekannter Schwächen.

**Dein Auftrag**

Arbeite dich in das Projekt ein und beurteile es. Wohin du dabei gehst, ist deine
Entscheidung — Produktgestaltung, Bedienung, Architektur, Modellwahl, Robustheit,
Wartbarkeit, Auslieferung, Barrierefreiheit, Datenschutz, Wirtschaftlichkeit, der
Vergleich mit vorhandenen Lösungen, oder etwas, das mir gar nicht in den Sinn
gekommen ist. Verteile deine Aufmerksamkeit so, wie es dem Gegenstand angemessen
ist, nicht gleichmäßig über Themenfelder.

Wenn du im Verlauf der Analyse zu dem Schluss kommst, dass die eigentliche Frage
eine andere ist als die, die ich dir stelle — sag das und beantworte die andere.

**Was eine brauchbare Antwort ausmacht**

- **Konkret statt allgemein.** „Mehr Tests schreiben" hilft nicht. „Der Weg X ist
  nicht abgesichert, weil Y — ein Fehler dort fiele erst beim Nutzer auf" schon.
- **Begründet.** Nenne, woraus du schließt. Wenn du etwas vermutest, ohne es
  belegen zu können, kennzeichne es als Vermutung.
- **Priorisiert.** Wenn nur drei Dinge umgesetzt würden — welche, und warum diese?
- **Ehrlich über Grenzen.** Wenn dir Information fehlt, um etwas zu beurteilen,
  benenne die Lücke, statt sie zu überbrücken.
- **Widerspruch erwünscht.** Wo eine Entscheidung aus deiner Sicht falsch ist,
  sag es direkt. Auch wenn sie im Briefing ausführlich begründet wird — gerade
  dann. Höflichkeit, die eine Schwäche verschweigt, ist wertlos.

**Was ich nicht brauche**

Eine Zusammenfassung dessen, was im Briefing steht. Eine Aufzählung generischer
Empfehlungen, die auf jedes Softwareprojekt zutreffen. Lob als Einleitung.

**Format**

Freie Form. Struktur und Länge wählst du so, wie es dem Inhalt entspricht.

**Der Ausgangspunkt**

Das Werkzeug funktioniert und wird täglich genutzt. Interessant ist deshalb nicht,
ob es läuft, sondern was jemand sieht, der nicht daran gebaut hat.
