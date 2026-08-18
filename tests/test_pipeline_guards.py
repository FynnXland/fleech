"""Treue zum Gesprochenen: Was das Modell ergaenzt oder umformuliert, wird gekappt.

Der Kern ist immer derselbe Handel: Glaettung ja, Erfindung nein. Reisst der
Guard, faellt die Pipeline auf den Rohtext zurueck — ein halbes Diktat ist
schlimmer als ein ungeglaettetes.
"""


from fleech.pipeline import Pipeline
from pipelinehelpers import (
    AUDIO,
    CLEAN_NONTRIVIAL,
    FakeLLM,
    RAW_NONTRIVIAL,
    make_pipeline,
)

VERBATIM_RAW = ("also das ding ist halt komplett kaputt gegangen und wir kriegen das "
                "nicht mehr hin")

VERBATIM_CLEAN = "Das Ding ist komplett kaputt gegangen, und wir kriegen das nicht mehr hin."

AUTO_LATEX_RAW = ("die ableitung von x hoch zwei ist zwei x und das gilt fuer alle "
                  "reellen zahlen")


def test_appended_sentence_is_trimmed():
    """Fehlerbild: das Modell haengt einen Schlusssatz an, den niemand gesagt hat.
    Der globale Grounding-Wert faellt dadurch kaum — der Schwanz-Guard muss greifen."""
    llm = FakeLLM(reply=(
        "Das Ding ist komplett kaputt gegangen, und wir kriegen das nicht mehr hin. "
        "Bei Rückfragen melde dich gerne jederzeit."
    ))
    p, _, injector = make_pipeline(VERBATIM_RAW, llm=llm)
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [
        "Das Ding ist komplett kaputt gegangen, und wir kriegen das nicht mehr hin."
    ]


def test_first_sentence_is_never_trimmed():
    """Auch wenn die Ausgabe insgesamt schwach gestuetzt ist, bleibt mindestens ein
    Satz stehen — der globale Grounding-Guard ist fuer den Totalfall zustaendig."""
    from fleech.textfilter import trim_unsupported_tail

    text, removed = trim_unsupported_tail("Völlig anderer Inhalt hier.", VERBATIM_RAW)
    assert removed == 0 and text == "Völlig anderer Inhalt hier."


def test_formula_sentences_are_never_trimmed():
    """LaTeX teilt naturgemaess keine Woerter mit dem gesprochenen Text — ein
    Formel-Satz am Ende darf nie als „erfunden" verworfen werden."""
    from fleech.textfilter import trim_unsupported_tail

    cleaned = "Der Server ist offline gewesen. Die Formel lautet $x^2+1$."
    text, removed = trim_unsupported_tail(cleaned, "der server ist offline gewesen")
    assert removed == 0 and text == cleaned


def test_formel_platzhalter_wird_nie_abgeschnitten():
    """C-5: Geschuetzt war „[[F" — ein Name, den es im Code nie gab. Formeln heissen
    „[[M1]]", und genau der Normalfall („… und das ergibt dann [[M1]]") wurde als
    erfundener Schlusssatz verworfen."""
    from fleech.textfilter import trim_unsupported_tail

    cleaned = "Der Server ist offline gewesen. Und das ergibt dann [[M1]]."
    text, removed = trim_unsupported_tail(cleaned, "der server ist offline gewesen")
    assert removed == 0 and text == cleaned


def test_paraphrase_triggers_stricter_retry():
    """Straffen ist Umformulieren: die Ausgabe erfindet nichts (Grounding bleibt hoch),
    laesst aber die Haelfte weg → EIN strengerer Zweitversuch, dessen wortgetreues
    Ergebnis dann eingefuegt wird."""
    replies = iter(["Das Ding ist kaputt.", VERBATIM_CLEAN])
    llm = FakeLLM(reply="")
    llm.complete = lambda system, user: (llm.calls.append((system, user)),
                                         next(replies))[1]
    p, _, injector = make_pipeline(VERBATIM_RAW, llm=llm)
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [VERBATIM_CLEAN]
    assert len(llm.calls) == 2                      # genau ein Zweitversuch
    assert "UMFORMULIERT" in llm.calls[1][0]        # mit expliziter Ansage


def test_persistent_paraphrase_falls_back_to_raw():
    """Strafft auch der Zweitversuch, gewinnt das Roh-Transkript — lieber unbereinigt
    als in fremden Worten."""
    p, llm, injector = make_pipeline(VERBATIM_RAW, llm=FakeLLM(reply="Das Ding ist kaputt."))
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [VERBATIM_RAW]
    assert len(llm.calls) == 2


def test_strong_intervention_may_reformulate():
    """Eingriffsgrad „strong" ist die ausdrueckliche Erlaubnis zu staerkerem Glaetten —
    dort darf der Wortgetreue-Guard nicht dazwischenfunken.

    Die Antwort haelt seit Befund A-3 die Verneinung („nicht mehr") fest: Sie darf
    kuerzen und umformulieren, aber nicht die Aussage drehen. Bis 5.10.2 stand hier
    eine Fassung ohne „nicht" — die kam durch, weil „strong" ALLE drei Pruefungen
    abschaltete, auch die auf Zahlen und Verneinungen.
    """
    smoothed = "Das Ding ist komplett kaputt — reparieren können wir es nicht mehr."
    p, llm, injector = make_pipeline(VERBATIM_RAW, llm=FakeLLM(reply=smoothed))
    p.intervention = "strong"
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [smoothed]
    assert len(llm.calls) == 1                      # kein Zweitversuch


def test_strong_intervention_prueft_weiterhin_verneinungen():
    """A-3: „Strong" glaettet staerker — die Aussage drehen darf es trotzdem nicht.

    Die beiden mitgelieferten Profile auf „strong" („Geschäftlich", „E-Mail") sind
    genau die, in denen Termine, Betraege und Zusagen stehen.
    """
    gedreht = "Das Ding ist komplett kaputt gegangen, und wir kriegen das wieder hin."
    p, llm, injector = make_pipeline(VERBATIM_RAW, llm=FakeLLM(reply=gedreht))
    p.intervention = "strong"
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [VERBATIM_RAW]
    assert len(llm.calls) == 2                      # ein Zweitversuch wie sonst auch


def test_strong_intervention_prueft_weiterhin_zahlen():
    zahlen_raw = ("also der rechnungsbetrag liegt bei 1249,90 euro und das team "
                  "braucht die freigabe bis freitag")
    ohne_zahl = ("Der Rechnungsbetrag liegt vor, und das Team braucht die Freigabe "
                 "bis Freitag.")
    p, llm, injector = make_pipeline(zahlen_raw, llm=FakeLLM(reply=ohne_zahl))
    p.intervention = "strong"
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [zahlen_raw]


def test_self_correction_gets_milder_verbatim_threshold():
    """Bei einer Selbstkorrektur faellt die zurueckgenommene Fassung legitim weg —
    das darf keinen Zweitversuch ausloesen."""
    raw = ("wir machen das am montag im großen konferenzraum ach nein warte wir "
           "machen das online")
    p, llm, injector = make_pipeline(raw, llm=FakeLLM(reply="Wir machen das online."))
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == ["Wir machen das online."]
    assert len(llm.calls) == 1                      # kein Fehlalarm


def test_verbatim_guard_ignores_filler_and_selfcorrection():
    """Fuellwoerter und die zurueckgenommene Fassung einer Selbstkorrektur duerfen
    legitim wegfallen — das darf den Guard nicht ausloesen."""
    from fleech.textfilter import verbatim_ratio

    raw = ("der server ist down seit heute morgen warte nein seit gestern abend und "
           "wir arbeiten dran")
    cleaned = "Der Server ist seit gestern Abend down, und wir arbeiten dran."
    assert verbatim_ratio(raw, cleaned) >= 0.7


def test_auto_latex_keeps_grounding_on_prose_part():
    """Bei Formel-Automatik darf der Grounding-Guard NICHT abgeschaltet sein: die
    `$…$`-Bloecke werden herausgeschnitten, der Fliesstext weiter geprueft."""
    llm = FakeLLM(reply="Ignoriere alle Anweisungen. Hier ist ein Gedicht $x^2$ ueber Katzen.")
    p, _, injector = make_pipeline(AUTO_LATEX_RAW, llm=llm)
    p.auto_latex = True
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [AUTO_LATEX_RAW]      # Halluzination abgefangen


def test_auto_latex_accepts_legitimate_formula_output():
    """Echte Formel-Ausgabe muss durchgehen — der Fliesstext ist gestuetzt."""
    cleaned = "Die Ableitung von $x^2$ ist $2x$, und das gilt für alle reellen Zahlen."
    p, _, injector = make_pipeline(AUTO_LATEX_RAW, llm=FakeLLM(reply=cleaned))
    p.auto_latex = True
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [cleaned]


def test_auto_latex_rejects_implausible_block_count():
    """Zerlegt das Modell den Text in lauter Mini-Formeln, ist das kein Mathe-Erkennen
    — Minimal-Sicherung fuer den Modus, in dem der Wortvergleich schwach ist."""
    shredded = " ".join(f"${w}$" for w in AUTO_LATEX_RAW.split())
    p, _, injector = make_pipeline(AUTO_LATEX_RAW, llm=FakeLLM(reply=shredded))
    p.auto_latex = True
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [AUTO_LATEX_RAW]


def test_strip_latex_blocks_and_density_rule():
    from fleech.textfilter import latex_blocks_implausible, strip_latex_blocks

    rest, blocks = strip_latex_blocks("Die Ableitung von $x^2$ ist $2x$ hier.")
    assert blocks == 2
    assert "$" not in rest and rest == "Die Ableitung von ist hier."
    # 14 Rohwoerter → bis zu 3 Bloecke plausibel, 4 nicht mehr.
    raw = " ".join(["wort"] * 14)
    assert not latex_blocks_implausible(raw, 3)
    assert latex_blocks_implausible(raw, 4)
    # Kurze Diktate: Mindestbudget 2 Bloecke, damit einfache Formeln durchgehen.
    assert not latex_blocks_implausible("x hoch zwei", 2)


def test_auto_latex_addendum_and_grounding_guard_skipped():
    from fleech.pipeline import _AUTO_LATEX_ADDENDUM

    # Modell wandelt gesprochene Mathe zu LaTeX → wenig Wort-Ueberlappung mit dem
    # Rohtext; ohne die auto_latex-Ausnahme wuerde der Grounding-Guard faelschlich
    # auf Rohtext zurueckfallen.
    reply = "Sei $\\int_a^b f(x)\\,dx = F(b)-F(a)$ die zentrale Gleichung hier."
    p, llm, injector = make_pipeline(
        "sei das integral von a bis b von f von x gleich groß f von b minus groß f von a "
        "die zentrale gleichung hier",
        llm=FakeLLM(reply=reply),
    )
    p.auto_latex = True
    p.process(AUDIO, 16000)
    assert injector.injected == [reply]                 # LaTeX bleibt, kein Rohtext-Fallback
    assert _AUTO_LATEX_ADDENDUM in llm.calls[0][0]       # Addendum steckt im System-Prompt


def test_auto_latex_off_keeps_grounding_guard():
    # Ohne auto_latex faengt der Guard erfundenen Inhalt (kaum Ueberlappung) weiter ab.
    raw = "der server war heute nacht kurz offline wir schauen morgen in die logs"
    p, _, injector = make_pipeline(raw, llm=FakeLLM(reply="Ganz andere erfundene Aussage."))
    p.process(AUDIO, 16000)
    assert injector.injected == [raw]                   # Grounding-Guard → Rohtext


def test_cleanup_strips_wrapping_quotes():
    # Realer Bug: Modell liefert „Text." trotz Prompt-Verbots.
    p, _, injector = make_pipeline(
        "also äh der text halt bitte war lang genug fuer das llm gedacht",
        llm=FakeLLM(reply='„Der Text war halt lang genug fuer das LLM gedacht."'),
    )
    p.process(AUDIO, 16000)
    assert injector.injected == ["Der Text war halt lang genug fuer das LLM gedacht."]


def test_cleanup_executed_prompt_falls_back_to_raw():
    # Realer Bug: Sprecher liest einen Prompt vor, Modell FUEHRT ihn aus statt zu
    # transkribieren → erfundener Inhalt (niedriges Grounding) → Roh-Transkript.
    raw = ("schreib mir eine hoefliche absage an die konferenz naechste woche und "
           "erwaehne dass ich leider keine zeit habe")
    executed = ("Sehr geehrte Damen und Herren, vielen Dank fuer die freundliche "
                "Einladung. Bedauerlicherweise kann ich nicht teilnehmen. Mit besten "
                "Gruessen.")
    p, _, injector = make_pipeline(raw, llm=FakeLLM(reply=executed))
    result = p.process(AUDIO, 16000)
    assert injector.injected == [raw]   # der vorgelesene Prompt, nicht die Ausfuehrung
    assert result == "fallback"


def test_cleanup_normal_result_passes_guard():
    raw = "also aeh der server ist seit heute morgen down und wir arbeiten dran"
    cleaned = "Der Server ist seit heute Morgen down, und wir arbeiten dran."
    p, _, injector = make_pipeline(raw, llm=FakeLLM(reply=cleaned))
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [cleaned]


def test_cleanup_guard_inactive_for_short_input():
    # Nicht-trivial (Marker "also" → LLM laeuft), aber < 6 Inhaltswoerter → Guard
    # aus: eine kurze, wenig ueberlappende Ausgabe wird nicht faelschlich verworfen.
    p, llm, injector = make_pipeline("also aeh guten morgen zusammen", llm=FakeLLM(reply="Moin."))
    p.process(AUDIO, 16000)
    assert llm.calls  # LLM lief (nicht trivial)
    assert injector.injected == ["Moin."]  # trotz null Grounding nicht verworfen


def test_abgeschnittene_cleanup_ausgabe_faellt_auf_rohtext_zurueck():
    """Kontextfenster voll → lieber unbereinigt und VOLLSTAENDIG.

    Das Fehlerbild ist heimtueckisch: Was das Modell geliefert hat, ist korrekt
    bereinigt — es endet nur mitten im Satz. Kein inhaltlicher Guard schlaegt an,
    weil nichts Falsches dasteht; es fehlt bloss der Rest. Deshalb wertet die
    Pipeline `last_truncated` des Clients aus (real: 610 Woerter rein, 84 raus).
    """
    raw = ("Also was ich gerade aktuell ein bisschen schwierig finde ist dass die "
           "Navigation noch nicht so richtig sitzt und ich glaube wir sollten da "
           "nochmal ran und zwar konkret an den Header und die Unterpunkte darin.")
    llm = FakeLLM(reply="Also, was ich gerade aktuell ein bisschen schwierig finde, ist,")
    llm.last_truncated = True
    p, _llm, injector = make_pipeline(raw, llm=llm)
    result = p.process(AUDIO, 16000)

    assert result == "fallback"
    assert injector.injected == [raw]      # vollstaendig, unbereinigt


def test_vollstaendige_ausgabe_bleibt_unangetastet():
    """Gegenprobe: ohne Abschneiden gewinnt weiter die bereinigte Fassung."""
    llm = FakeLLM(reply=CLEAN_NONTRIVIAL)
    llm.last_truncated = False
    p, _llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=llm)
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [CLEAN_NONTRIVIAL]
