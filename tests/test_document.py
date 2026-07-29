from fleech.document import DocumentTracker


def make_tracker():
    t = DocumentTracker()
    t._window = 42  # Fenster-Logik in Unit-Tests neutralisieren
    return t


def test_separator_only_after_text():
    t = make_tracker()
    assert t.separator() == ""
    t.record_append("Erster Satz.")
    assert t.separator() == " "
    t.record_append("\n")
    assert t.separator() == ""


def test_record_append_and_context():
    t = make_tracker()
    t.record_append("Hallo Welt.")
    t.record_append(" Zweiter Satz.")
    assert t.text == "Hallo Welt. Zweiter Satz."
    assert t.context_tail(12) == "weiter Satz."


def test_scope_dictated_is_last_chunk():
    t = make_tracker()
    t.record_append("Alter Text.")
    t.record_append(" Neuer Text.")
    assert t.resolve_scope("dictated") == " Neuer Text."


def test_scope_whole_document():
    t = make_tracker()
    t.record_append("A. B.")
    assert t.resolve_scope("whole_document") == "A. B."


def test_scope_last_sentence():
    t = make_tracker()
    t.record_append("Der erste Satz. Der zweite Satz! Und der dritte Satz.")
    assert t.resolve_scope("last_sentence") == "Und der dritte Satz."


def test_scope_last_sentence_single_sentence():
    t = make_tracker()
    t.record_append("Nur ein Satz ohne Ende")
    assert t.resolve_scope("last_sentence") == "Nur ein Satz ohne Ende"


def test_scope_last_paragraph():
    t = make_tracker()
    t.record_append("Absatz eins.\nAbsatz zwei mit mehr Text.")
    assert t.resolve_scope("last_paragraph") == "Absatz zwei mit mehr Text."


def test_scope_last_paragraph_without_newline_is_all():
    t = make_tracker()
    t.record_append("Nur ein Absatz.")
    assert t.resolve_scope("last_paragraph") == "Nur ein Absatz."


def test_unresolvable_scopes():
    t = make_tracker()
    assert t.resolve_scope("whole_document") is None  # leerer Puffer
    t.record_append("Text.")
    assert t.resolve_scope("as_described") is None
    assert t.resolve_scope("quatsch") is None


def test_record_replace_updates_buffer_and_last_chunk():
    t = make_tracker()
    t.record_append("Der Umsatz stieg um 20 Prozent.")
    t.record_replace(len("Der Umsatz stieg um 20 Prozent."), "Der Umsatz verzeichnete einen Anstieg.")
    assert t.text == "Der Umsatz verzeichnete einen Anstieg."
    assert t.resolve_scope("dictated") == "Der Umsatz verzeichnete einen Anstieg."


def test_window_change_resets_buffer(monkeypatch):
    t = DocumentTracker()
    monkeypatch.setattr(DocumentTracker, "_foreground_window", staticmethod(lambda: 1))
    t.sync_window()
    t.record_append("Text im ersten Fenster.")
    t.sync_window()  # gleiches Fenster → bleibt
    assert t.text == "Text im ersten Fenster."
    monkeypatch.setattr(DocumentTracker, "_foreground_window", staticmethod(lambda: 2))
    t.sync_window()  # anderes Fenster → Reset
    assert t.text == ""


# -- Thread-Sicherheit ------------------------------------------------------------
# Der Qt-Signal-Bus serialisiert nur UI-Ereignisse, NICHT den Zugriff mehrerer Worker
# auf diesen Puffer. Ueberlappen zwei Diktat-Verarbeitungen, schreiben beide hier —
# ohne Lock waere der Bezugspunkt fuer Safe-Word-Ersetzungen falsch.


def test_all_public_methods_take_the_lock():
    """Deterministisch statt probabilistisch: jede oeffentliche Methode muss den
    Lock anfassen (ein vergessener Pfad faellt so sofort auf)."""
    import threading

    class CountingLock:
        def __init__(self):
            self._inner = threading.RLock()
            self.acquired = 0

        def __enter__(self):
            self.acquired += 1
            return self._inner.__enter__()

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

    t = make_tracker()
    t.record_append("Ein Satz. Noch einer.")
    lock = CountingLock()
    t._lock = lock

    calls = (
        lambda: t.text,
        lambda: t.context_tail(),
        lambda: t.separator(),
        lambda: t.record_append("x"),
        lambda: t.record_replace(1, "y"),
        lambda: t.resolve_scope("dictated"),
        lambda: t.sync_window(),
    )
    for i, call in enumerate(calls, start=1):
        call()
        assert lock.acquired == i, f"Aufruf {i} hat den Lock nicht genommen"


def test_concurrent_appends_keep_buffer_consistent():
    """Lasttest: parallele Anhaenge duerfen sich nie gegenseitig ueberschreiben."""
    import threading

    t = make_tracker()
    threads = [
        threading.Thread(target=lambda: [t.record_append("ab") for _ in range(200)])
        for _ in range(8)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(t.text) == 8 * 200 * 2
    assert set(t.text) == {"a", "b"}


# -- Session-Kontext ueber Fensterwechsel (W3-15) ---------------------------------

def make_windowed_tracker():
    """Tracker mit steuerbarem Vordergrund-Fenster."""
    t = DocumentTracker()
    t._fake_hwnd = 1
    t._foreground_window = lambda: t._fake_hwnd
    t._window_alive = lambda hwnd: True
    t.sync_window()
    return t


def test_rueckkehr_bringt_kontext_zurueck_aber_keine_ersetzung():
    t = make_windowed_tracker()
    t.record_append("Erster Satz im Editor.")
    assert t.resolve_scope("last_sentence")           # normale Sitzung: ersetzbar

    t._fake_hwnd = 2                                  # kurz in den Browser …
    t.sync_window()
    assert t.text == ""                               # dort: frischer Kontext

    t._fake_hwnd = 1                                  # … und zurueck
    t.sync_window()
    assert "Erster Satz" in t.context_tail()          # Lese-Kontext ist wieder da
    # Aber: Cursor-Position unbekannt → JEDER Ersetzungs-Scope liefert None.
    for scope in ("dictated", "last_sentence", "last_paragraph", "whole_document"):
        assert t.resolve_scope(scope) is None


def test_eigene_injection_erlaubt_ersetzungen_wieder():
    t = make_windowed_tracker()
    t.record_append("Alter Text.")
    t._fake_hwnd = 2
    t.sync_window()
    t._fake_hwnd = 1
    t.sync_window()
    assert t.resolve_scope("dictated") is None        # dirty
    t.record_append(" Neuer Satz.")                   # eigene Injection → Cursor bekannt
    assert t.resolve_scope("dictated") == " Neuer Satz."
    assert "Alter Text." in t.resolve_scope("whole_document")


def test_timeout_verwirft_session(monkeypatch):
    import fleech.document as doc

    t = make_windowed_tracker()
    t.record_append("Vergesslicher Text.")
    t._fake_hwnd = 2
    t.sync_window()
    # Uhr ueber den Timeout hinausdrehen.
    real = doc.time.monotonic
    monkeypatch.setattr(doc.time, "monotonic",
                        lambda: real() + doc.SESSION_TIMEOUT_S + 1)
    t._fake_hwnd = 1
    t.sync_window()
    assert t.text == ""                               # verfallen, kein Kontext


def test_session_info_fuer_die_pille():
    t = make_windowed_tracker()
    assert t.session_info() is None                   # noch nichts diktiert
    t.record_append("Eins.")
    t.record_append(" Zwei.")
    chunks, minutes, nur_lesbar = t.session_info()
    assert chunks == 2 and minutes == 0
    assert nur_lesbar is False        # eigene Injection → Ersetzen erlaubt
    t._fake_hwnd = 2
    t.sync_window()
    assert t.session_info() is None                   # neues Fenster: kein Kontext
    t._fake_hwnd = 1
    t.sync_window()
    # Rueckkehr: Kontext wird gemeldet, aber als NUR LESBAR — die Cursor-Position
    # ist unbekannt, deshalb verweigert `resolve_scope` das Ersetzen. Die Pille
    # zeigt das jetzt VORHER (hohler Satellit), statt den Befehl scheitern zu lassen.
    assert t.session_info() == (2, 0, True)
    assert t.resolve_scope("dictated") is None        # und zwar konsistent dazu


def test_session_deckel_wirft_die_aelteste_raus():
    t = make_windowed_tracker()
    for i in range(1, 12):                            # 11 Fenster > Deckel 8
        t._fake_hwnd = i
        t.sync_window()
        t.record_append(f"Fenster {i}.")
    assert len(t._sessions) <= 8
    assert 11 in t._sessions                          # die aktive fliegt nie


def test_tote_fenster_werden_aufgeraeumt():
    t = make_windowed_tracker()
    t.record_append("Lebt noch.")
    t._fake_hwnd = 2
    t._window_alive = lambda hwnd: hwnd != 1          # Fenster 1 ist zu
    t.sync_window()
    assert 1 not in t._sessions


def test_text_deckel_behaelt_das_ende():
    import fleech.document as doc

    t = make_windowed_tracker()
    t.record_append("A" * (doc._MAX_SESSION_CHARS + 500) + " Ende.")
    assert len(t.text) <= doc._MAX_SESSION_CHARS
    assert t.text.endswith("Ende.")
