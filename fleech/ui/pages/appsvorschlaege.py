"""Zuordnungsvorschläge aus dem eigenen Verlauf (Vorschlag V-13, G-4 + H-7).

In 1399 Diktaten über 25 Anwendungen ist **keine einzige** App→Profil-Zuordnung
entstanden — obwohl die Mechanik seit Langem steht und derselbe Nutzer 220-mal von
Hand ein Profil gewählt hat. Die Zuordnung verlangt heute, dass man von selbst auf
die Apps-Seite geht, die richtige Anwendung in dreißig Zeilen findet und weiß,
welches Profil passt. Was Vorab-Handarbeit verlangt, passiert nicht.

Deshalb eine Karte, die die Frage stellt, statt auf sie zu warten:

    „In claude.exe hast du 895 Diktate gemacht (64 % aller). Kein Profil
     zugewiesen." → [KI-Prompt zuweisen] [Standard] [Nicht mehr fragen]

Zwei Regeln, die nicht verhandelbar sind:

* **Nie automatisch zuweisen.** Ein Vorschlag, der sich selbst übernimmt, ändert
  über Nacht, was beim Diktieren herauskommt.
* **Ablehnung ist dauerhaft** (`profiles.vorschlag_ignores`, dasselbe Muster wie
  `output.dictionary_ignores`). Eine Karte, die man nicht wegbekommt, ist
  schlimmer als keine.

Kein Qt: Die Regel ist reine Rechnerei über Verlauf und Profile und lässt sich
damit gegen eine Test-History prüfen, ohne ein Fenster zu bauen.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...profiles import parse_app_rule, profile_mode

# Ab wie vielen Diktaten eine Anwendung überhaupt gefragt wird. Bewusst hoch: Bei
# 25 Diktaten ist die Anwendung ein Arbeitsort und kein Zufall — im echten Verlauf
# trifft das fünf von 25 Anwendungen.
MIN_DIKTATE = 25

# Wann gilt ein von Hand gewähltes Profil als Muster? Beides muss stimmen, sonst
# schlägt eine Handvoll Ausreißer eine Regel für den Alltag vor.
MIN_PROFIL_DIKTATE = 8
PROFIL_ANTEIL = 0.7

# Wie oft ein Ausgabeformat vorgekommen sein muss, damit es den Vorschlag prägt.
MIN_FORMAT_TREFFER = 2

# Höchstens zwei Karten gleichzeitig. Drei Fragen auf einmal beantwortet niemand.
MAX_VORSCHLAEGE = 2

# Für den Begründungssatz — die Profile heißen beim Nutzer, wie er sie nennt.
_FORMAT_NAMEN = {"prompt": "KI-Prompt", "summary": "Stichpunkte", "email": "E-Mail"}


@dataclass
class Vorschlag:
    """Eine Karte: welche Anwendung, wie viel, welches Profil, und warum."""

    app: str
    diktate: int
    anteil: float           # Anteil an allen Diktaten mit bekannter Anwendung
    profil: str             # vorgeschlagenes Profil (der erste Knopf)
    alternative: str = ""   # zweiter Knopf ("" = keiner)
    grund: str = ""         # warum gerade dieses Profil ("" = kein Muster)

    def satz(self) -> str:
        prozent = f" ({self.anteil * 100:.0f} % aller)" if self.anteil else ""
        satz = (f"In {self.app} hast du {self.diktate} Diktate gemacht{prozent}. "
                f"Kein Profil zugewiesen.")
        return f"{satz} {self.grund}".strip()


def zugewiesene_apps(items) -> set:
    """Prozessnamen (klein), für die es IRGENDEINE Regel gibt — mit oder ohne Titel.

    Auch eine reine Titel-Ausnahme zählt: Wer sich dort schon Gedanken gemacht
    hat, braucht keine Karte, die ihm dieselbe Anwendung noch einmal anbietet.
    """
    treffer = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for eintrag in item.get("apps", []):
            prozess = parse_app_rule(eintrag)[0].strip().lower()
            if prozess:
                treffer.add(prozess)
    return treffer


def _profil_namen(items) -> tuple[dict, str]:
    """({Ausgabeformat: Profilname}, Name des Standardprofils)."""
    nach_format: dict = {}
    standard = ""
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        if item.get("default") and not standard:
            standard = name
        mode = profile_mode(item)
        if mode and mode not in nach_format:
            nach_format[mode] = name
    return nach_format, standard


def _kandidaten(nutzung, items) -> tuple[list, str]:
    """Profilnamen in der Reihenfolge, in der sie vorgeschlagen werden — und der
    Begründungssatz zum ersten.

    Drei Quellen, in dieser Rangfolge:
      1. das von Hand gewählte Profil dieser Anwendung (seit 5.10.4 im Verlauf) —
         die stärkste Aussage, weil sie eine Entscheidung war;
      2. das Ausgabeformat, in dem dort tatsächlich diktiert wurde;
      3. das Standardprofil, damit „hier ist normal richtig" auch eine Antwort ist.
    """
    nach_format, standard = _profil_namen(items)
    bekannt = {str(i.get("name", "")).strip().lower()
               for i in items or [] if isinstance(i, dict)}
    namen: list = []
    grund = ""

    mit_profil = sum((nutzung.profile or {}).values())
    if mit_profil:
        sieger, treffer = max(nutzung.profile.items(), key=lambda p: p[1])
        if (treffer >= MIN_PROFIL_DIKTATE and treffer / mit_profil >= PROFIL_ANTEIL
                and str(sieger).lower() in bekannt):
            namen.append(str(sieger))
            grund = (f"Dort nimmst du {treffer} von {mit_profil} Mal "
                     f"„{sieger}“ von Hand.")

    for mode, anzahl in sorted((nutzung.modi or {}).items(), key=lambda p: -p[1]):
        name = nach_format.get(mode)
        if not name or anzahl < MIN_FORMAT_TREFFER:
            continue
        if name.lower() in {n.lower() for n in namen}:
            continue
        namen.append(name)
        if not grund:
            grund = (f"{anzahl} davon liefen als "
                     f"{_FORMAT_NAMEN.get(mode, mode)}.")

    if standard and standard.lower() not in {n.lower() for n in namen}:
        namen.append(standard)
    return namen, grund


def vorschlaege(nutzung_liste, gesamt: int, items, ignoriert=()) -> list:
    """Welche Anwendungen sollte man fragen? Höchstens `MAX_VORSCHLAEGE`.

    `nutzung_liste` sind `history.AppNutzung`-Einträge (meistgenutzte zuerst),
    `gesamt` die Gesamtzahl der Diktate mit bekannter Anwendung.
    """
    zugewiesen = zugewiesene_apps(items)
    weg = {str(a).strip().lower() for a in (ignoriert or ())}
    treffer = []
    for nutzung in nutzung_liste or []:
        schluessel = str(nutzung.app).strip().lower()
        if not schluessel or schluessel in zugewiesen or schluessel in weg:
            continue
        if nutzung.diktate < MIN_DIKTATE:
            continue
        namen, grund = _kandidaten(nutzung, items)
        if not namen:
            continue          # keine Profile da — dann gibt es nichts zuzuweisen
        treffer.append(Vorschlag(
            app=nutzung.app, diktate=nutzung.diktate,
            anteil=(nutzung.diktate / gesamt) if gesamt else 0.0,
            profil=namen[0], alternative=namen[1] if len(namen) > 1 else "",
            grund=grund,
        ))
        if len(treffer) >= MAX_VORSCHLAEGE:
            break
    return treffer
