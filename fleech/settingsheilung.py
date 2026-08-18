"""Erkennt, ob eine gueltige settings.json in Wahrheit ein Ruecksetzer ist — und
sagt beim Start, was tatsaechlich geladen wurde.

Warum eigenstaendig: `usersettings.py` ist Feldablage plus Persistenz. Die Frage
„ist diese Datei aermer als ihre Sicherung, und zwar so, wie es kein Mensch
bedient haette?" ist echte Logik mit eigenen Regeln — genau die Sorte Thema, aus
der dort schon einmal ein 294-Zeilen-Block gewachsen ist.

Richtung der Abhaengigkeit: `usersettings` importiert von hier, nie umgekehrt.
Dieses Modul kennt weder Pfade noch das Schreiben; das UserSettings bekommt es
als Fabrik gereicht.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Hotkeys, die der Nutzer belegt haben kann. Zusammen mit Lizenz, Onboarding,
# Woerterbuch, Bausteinen, Schnellwechsel und Profilliste bilden sie den
# „wertvollen" Teil der Einstellungen — nur an ihm wird gemessen (Befund A-5).
HOTKEY_FELDER = ("hotkey", "prompt_toggle_hotkey", "undo_hotkey", "pause_hotkey",
                 "profile_hotkey")


def wende_an(settings, data) -> None:
    """Abschnitte einer settings.json auf ein UserSettings legen.

    Unbekannte Abschnitte und Schluessel werden uebergangen — so bleiben aeltere
    und neuere Dateien gegenseitig lesbar."""
    for section_name, section_data in (data or {}).items():
        section = getattr(settings, section_name, None)
        if section is None or not isinstance(section_data, dict):
            continue
        for key, value in section_data.items():
            if hasattr(section, key):
                setattr(section, key, value)


def wertvoller_abzug(fabrik, data) -> dict:
    """Die wertvollen Felder einer Fassung als vergleichbarer Abzug.

    Bewusst ueber ein echtes UserSettings statt direkt aus dem Dict: Ein fehlendes
    Feld in der Datei bedeutet „Vorgabe", und genau so muss es sich hier auch
    verhalten — sonst waere eine schlanke Datei faelschlich „aermer" als die
    Vorgaben."""
    s = fabrik()
    wende_an(s, data)
    return {
        "lizenz": str(s.general.license_key or ""),
        "onboarding": bool(s.general.onboarding_done),
        "woerterbuch": list(s.output.dictionary or []),
        "bausteine": list(s.output.snippets or []),
        "app_quick": dict(s.profiles.app_quick or {}),
        "profile": list(s.profiles.items or []),
        "hotkeys": {n: str(getattr(s.recording, n, "") or "") for n in HOTKEY_FELDER},
    }


def ist_zurueckgesetzt(data, sicherung, fabrik) -> bool:
    """Ist `data` ein Ruecksetzer auf Vorgaben, waehrend die Sicherung noch alles hat?

    Der reale Fall (Befund A-5): Am 17.08. stand die settings.json zweimal auf
    Vorgaben — Lizenz weg, Diktat-Hotkey wieder f9 — und die gute Fassung lag als
    .bak daneben. `load()` hat sie nicht gezogen, weil die Datei ja gueltiges JSON
    war; der naechste `save()` machte die Vorgaben endgueltig.

    Zwei Kriterien, beide absichtlich eng:
      (a) Lizenzschluessel in der Datei leer, in der Sicherung gesetzt. Ein
          Schluessel verschwindet nicht durch Bedienung — dafuer gibt es keinen
          Knopf.
      (b) Die Datei ist auf ALLEN wertvollen Feldern der Auslieferungszustand und
          die Sicherung weicht in mindestens ZWEI davon ab.

    Warum so eng: Einzelne Werte darf man zuruecksetzen — wer sein Woerterbuch
    leert, will es geleert haben. Erst wenn alles auf einmal auf Werk steht, war
    es kein Mensch.
    """
    datei = wertvoller_abzug(fabrik, data)
    bak = wertvoller_abzug(fabrik, sicherung)
    if datei == bak:
        return False
    if not datei["lizenz"] and bak["lizenz"]:
        return True
    werk = wertvoller_abzug(fabrik, {})
    if datei != werk:
        return False
    return sum(1 for feld in werk if bak[feld] != werk[feld]) >= 2


def protokolliere_umfang(settings) -> None:
    """Was tatsaechlich geladen wurde, in einer Zeile (Befund B10).

    Anlass: Die einzige je angelegte Schnellwechsel-Zuordnung war zweimal weg,
    ohne dass es irgendwo aufgefallen waere — es gibt keine Anzeige „hier ist
    nichts konfiguriert, obwohl du mal etwas konfiguriert hattest". Diese Zeile
    macht den Verlust beim naechsten Blick ins Log sichtbar."""
    items = [i for i in (settings.profiles.items or []) if isinstance(i, dict)]
    quick = settings.profiles.app_quick
    quick = quick if isinstance(quick, dict) else {}
    log.info("Einstellungen geladen: %d Profile, %d App-Zuordnungen, "
             "%d Schnellwechsel-Apps (%d Eintraege), %d Woerterbuchzeilen, "
             "Lizenz %s.",
             len(items),
             sum(len(i.get("apps") or []) for i in items),
             len(quick),
             sum(len(v or []) for v in quick.values() if isinstance(v, (list, tuple))),
             len(settings.output.dictionary or []),
             "vorhanden" if str(settings.general.license_key or "").strip() else "FEHLT")
