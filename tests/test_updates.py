"""Update-Weg: Version vergleichen, Quelle pruefen, Datei verifizieren.

Schwerpunkt sind die Sicherheitsregeln — ein Update ist der einzige Weg, auf dem
Fleech fremden Code auf den Rechner holt. Alles, was dabei nicht stimmt, muss zum
Verwerfen fuehren, nicht zu einem Versuch.
"""

import hashlib
from pathlib import Path

from fleech.ui import updates
from fleech.ui.updates import check_for_updates, download_update, is_newer


def test_version_comparison():
    assert is_newer("1.1.0", "1.0.0")
    assert is_newer("1.0.1", "1.0.0")
    assert is_newer("2.0.0", "1.9.9")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("0.9.0", "1.0.0")


# -- Quelle pruefen ----------------------------------------------------------------


def test_http_quelle_wird_abgelehnt():
    """Ohne TLS koennte jeder im Netz die Datei austauschen."""
    result = check_for_updates("http://beispiel.test/feed.json")
    assert result["status"] == "error"
    assert "HTTPS" in result["message"]


def test_bad_feed_url_returns_error_not_crash():
    result = check_for_updates("https://127.0.0.1:9/nope.json", timeout=0.5)
    assert result["status"] == "error"
    assert result["current"]


def _github(monkeypatch, data):
    monkeypatch.setattr(updates, "_fetch_json", lambda url, timeout: data)


def test_github_release_wird_gelesen(monkeypatch):
    _github(monkeypatch, {
        "tag_name": "v99.0.0",
        "body": "Fleech 99\n\nSHA256: " + "ab" * 32 + "\n",
        "assets": [
            {"name": "liesmich.txt", "size": 5,
             "browser_download_url": "https://github.com/x/y/liesmich.txt"},
            {"name": "FleechSetup-99.0.0.exe", "size": 123456,
             "browser_download_url":
                 "https://github.com/x/y/releases/download/v99/FleechSetup-99.0.0.exe"},
        ],
    })
    result = check_for_updates()
    assert result["status"] == "update_available"
    assert result["latest"] == "99.0.0"
    assert result["url"].endswith("FleechSetup-99.0.0.exe")   # nicht die txt-Datei
    assert result["size"] == 123456
    assert result["sha256"] == "ab" * 32


def test_aeltere_version_ist_aktuell(monkeypatch):
    _github(monkeypatch, {"tag_name": "v0.0.1", "assets": []})
    assert check_for_updates()["status"] == "up_to_date"


def test_release_ohne_setup_datei_ist_kein_update(monkeypatch):
    """Ein Tag ohne Installer darf nicht als installierbares Update erscheinen."""
    _github(monkeypatch, {"tag_name": "v99.0.0", "assets": []})
    result = check_for_updates()
    assert result["status"] == "error"
    assert "ohne Installationsdatei" in result["message"]


def test_repo_ohne_release_ist_kein_fehler(monkeypatch):
    class NotFound(Exception):
        code = 404

    def kaputt(url, timeout):
        raise NotFound()

    monkeypatch.setattr(updates, "_fetch_json", kaputt)
    assert check_for_updates()["status"] == "no_release"


def test_fremder_download_host_wird_abgelehnt(monkeypatch):
    """Die Quelle darf nicht auf eine Datei ausserhalb ihrer Herkunft zeigen."""
    _github(monkeypatch, {
        "tag_name": "v99.0.0",
        "assets": [{"name": "FleechSetup-99.0.0.exe", "size": 1,
                    "browser_download_url": "https://boese.test/FleechSetup-99.0.0.exe"}],
    })
    result = check_for_updates()
    assert result["status"] == "error"
    assert "gehört nicht" in result["message"]


def test_eigener_feed_wird_gelesen(monkeypatch):
    monkeypatch.setattr(updates, "_fetch_json", lambda url, timeout: {
        "version": "99.0.0", "url": "https://eigen.test/FleechSetup.exe",
        "sha256": "cd" * 32, "size": 10,
    })
    result = check_for_updates("https://eigen.test/feed.json")
    assert result["status"] == "update_available"
    assert result["sha256"] == "cd" * 32


def test_eigener_feed_darf_nicht_auf_fremden_host_zeigen(monkeypatch):
    monkeypatch.setattr(updates, "_fetch_json", lambda url, timeout: {
        "version": "99.0.0", "url": "https://woanders.test/FleechSetup.exe",
    })
    assert check_for_updates("https://eigen.test/feed.json")["status"] == "error"


# -- Download verifizieren ---------------------------------------------------------

INHALT = b"FLEECH-SETUP-TESTDATEI" * 100
HASH = hashlib.sha256(INHALT).hexdigest()


class _Antwort:
    """Minimaler urlopen-Ersatz (Kontextmanager mit read/geturl/headers)."""

    def __init__(self, inhalt=INHALT, url="https://github.com/x/FleechSetup-9.exe"):
        self._rest = inhalt
        self._url = url
        self.headers = {"Content-Length": str(len(inhalt))}

    def read(self, n=-1):
        block, self._rest = self._rest[:n], self._rest[n:]
        return block

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen(monkeypatch, antwort_factory):
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda req, timeout=0: antwort_factory())


def test_download_prueft_summe_und_groesse(monkeypatch, tmp_path):
    _urlopen(monkeypatch, _Antwort)
    fortschritt = []
    ziel = download_update("https://github.com/x/FleechSetup-9.exe", tmp_path,
                           on_progress=lambda p, t: fortschritt.append(p),
                           expected_size=len(INHALT), expected_sha256=HASH)
    assert ziel is not None and ziel.read_bytes() == INHALT
    assert 100 in fortschritt


def test_download_verwirft_bei_falscher_pruefsumme(monkeypatch, tmp_path):
    """Der wichtigste Test hier: falsche Summe = Datei weg, kein Installer."""
    _urlopen(monkeypatch, _Antwort)
    assert download_update("https://github.com/x/FleechSetup-9.exe", tmp_path,
                           expected_sha256="00" * 32) is None
    assert list(Path(tmp_path).glob("*.exe")) == []


def test_download_verwirft_bei_falscher_groesse(monkeypatch, tmp_path):
    _urlopen(monkeypatch, _Antwort)
    assert download_update("https://github.com/x/FleechSetup-9.exe", tmp_path,
                           expected_size=len(INHALT) + 1) is None
    assert list(Path(tmp_path).glob("*.exe")) == []


def test_download_lehnt_weiterleitung_auf_fremden_host_ab(monkeypatch, tmp_path):
    """Die Host-Sperre gilt fuer das ZIEL der Weiterleitung, nicht nur den Anfang."""
    _urlopen(monkeypatch, lambda: _Antwort(url="https://boese.test/setup.exe"))
    assert download_update("https://github.com/x/FleechSetup-9.exe", tmp_path,
                           expected_sha256=HASH) is None


def test_download_lehnt_http_ab(tmp_path):
    assert download_update("http://github.com/x/FleechSetup-9.exe", tmp_path) is None


def test_download_ohne_pruefsumme_laeuft_mit_groessenpruefung(monkeypatch, tmp_path):
    """Kein Hash veroeffentlicht: erlaubt, aber im Log vermerkt — sonst waere ein
    Release ohne Notizen ein Totalausfall."""
    _urlopen(monkeypatch, _Antwort)
    assert download_update("https://github.com/x/FleechSetup-9.exe", tmp_path,
                           expected_size=len(INHALT)) is not None


def test_download_bricht_bei_netzfehler_ohne_ruine_ab(monkeypatch, tmp_path):
    class Kaputt(_Antwort):
        def read(self, n=-1):
            raise OSError("Verbindung weg")

    _urlopen(monkeypatch, Kaputt)
    assert download_update("https://github.com/x/FleechSetup-9.exe", tmp_path) is None
    assert list(Path(tmp_path).glob("*.exe")) == []


def test_install_update_ohne_datei_ist_false(tmp_path):
    from fleech.ui.updates import install_update

    assert install_update(tmp_path / "gibtsnicht.exe") is False


# -- Einstellungen -----------------------------------------------------------------


def test_automatische_pruefung_ist_an_installation_nicht():
    """Pruefen und Laden duerfen automatisch sein — Installieren nie."""
    from fleech.usersettings import AdvancedSettings

    s = AdvancedSettings()
    assert s.auto_update_check is True
    assert s.auto_update_download is True
    assert s.update_feed_url == ""        # leer = GitHub-Releases des Projekts
