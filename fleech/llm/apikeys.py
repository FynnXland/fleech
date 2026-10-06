"""API-Schluessel ablegen und lesen — nie im Klartext neben den Einstellungen.

Ablage ist der Schluesselbund des Systems (`keyring`): unter Windows die
Anmeldeinformationsverwaltung, unter Linux der Secret Service (KWallet/GNOME
Schluesselbund). `settings.json` traegt nur, WELCHER Anbieter gewaehlt ist — die
Datei wird gesichert, kopiert und mitunter verschickt, ein Schluessel darin waere
mit ihr unterwegs.

Rueckfall in dieser Reihenfolge, damit auch Entwickler und Server ohne
Schluesselbund durchkommen:
  1. Schluesselbund (Dienst "Fleech", Konto = Anbieter-Kennung)
  2. die Umgebungsvariable, die der Anbieter selbst dokumentiert (OPENAI_API_KEY …)
  3. FLEECH_<ANBIETER>_API_KEY (auch aus `%APPDATA%\\Fleech\\.env`)

Kein Schluessel erscheint je im Log.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

DIENST = "Fleech"


def _bund():
    try:
        import keyring

        return keyring
    except Exception:
        log.debug("keyring nicht verfuegbar.", exc_info=True)
        return None


def lies(anbieter_id: str) -> str:
    """Der Schluessel fuer diesen Anbieter, oder leer."""
    from .providers import anbieter

    bund = _bund()
    if bund is not None:
        try:
            wert = bund.get_password(DIENST, anbieter_id)
            if wert:
                return wert.strip()
        except Exception:
            log.debug("Schluesselbund nicht lesbar.", exc_info=True)
    eintrag = anbieter(anbieter_id)
    for name in (eintrag.umgebung, f"FLEECH_{anbieter_id.upper()}_API_KEY"):
        if name and os.environ.get(name, "").strip():
            return os.environ[name].strip()
    return ""


def speichere(anbieter_id: str, schluessel: str) -> bool:
    """Ablegen; leerer Schluessel = entfernen. False = kein Schluesselbund da.

    Bei False sagt die Oberflaeche ehrlich, dass der Schluessel nur ueber eine
    Umgebungsvariable geht — statt ihn stillschweigend in eine Datei zu schreiben.
    """
    bund = _bund()
    if bund is None:
        return False
    schluessel = (schluessel or "").strip()
    try:
        if schluessel:
            bund.set_password(DIENST, anbieter_id, schluessel)
            log.info("API-Schluessel fuer %s im Schluesselbund abgelegt.", anbieter_id)
        else:
            try:
                bund.delete_password(DIENST, anbieter_id)
                log.info("API-Schluessel fuer %s entfernt.", anbieter_id)
            except Exception:
                pass                    # war gar keiner da
        return True
    except Exception:
        log.warning("Schluesselbund nicht beschreibbar.", exc_info=True)
        return False


def maskiert(schluessel: str) -> str:
    """Zur Anzeige: Anfang und Ende, die Mitte nie („sk-…3f9a")."""
    s = (schluessel or "").strip()
    if len(s) < 12:
        return "•" * len(s)
    return f"{s[:4]}…{s[-4:]}"
