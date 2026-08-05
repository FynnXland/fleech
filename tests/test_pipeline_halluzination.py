"""Erfundene Schwaenze: Wiederholungsschleifen, Kauderwelsch, fremde Schrift,
Sinnumkehr.

Anders als die Guards in test_pipeline_guards.py geht es hier nicht um zu
freie Formulierung, sondern um Text, den NIEMAND gesagt hat — meist aus
auslaufendem oder stillem Audio.
"""


from pipelinehelpers import AUDIO, FakeLLM, make_pipeline

def test_whisper_repetition_loop_is_collapsed():
    """Whisper haengt auf auslaufendem Audio denselben Satz dutzendfach an (real im
    Log beobachtet) — das ist ein Artefakt und wird auf EINE Nennung gekuerzt."""
    from fleech.textfilter import collapse_trailing_repetitions

    raw = "Okay, das schicke ich dir rüber. " + "Das war's. " * 12
    assert collapse_trailing_repetitions(raw) == "Okay, das schicke ich dir rüber. Das war's."
    # ohne Satzzeichen ebenso
    assert collapse_trailing_repetitions("also gut " + "und so weiter " * 6).endswith(
        "also gut und so weiter"
    )
    # echte Rhetorik ueberlebt: dreifaches Einzelwort bleibt stehen
    assert collapse_trailing_repetitions("das geht so nicht nein nein nein") == \
        "das geht so nicht nein nein nein"
    # zweifache Wiederholung ist keine Schleife
    assert collapse_trailing_repetitions("bis dann. bis dann.") == "bis dann. bis dann."


def test_hallucinated_tail_is_dropped():
    """Zerfallener Schwanz OHNE saubere Schleife — der zweite Halluzinations-Typ.

    Wortlaut aus dem echten Log (Diktat 13:57:06): Die Erkennung franst aus und
    wiederholt ein Fachwort verstreut, mit Sprachwechseln dazwischen. Kein
    Teilstueck wiederholt sich unmittelbar, also greift der Schleifen-Guard nicht.
    """
    from fleech.textfilter import strip_hallucinated_tail

    raw = ("Aber ja, da weiß ich wohl der Fehler, aber kannst du es selber in meiner "
           "Datei einmal korrigieren? Am besten in perfekter Klausulnotation zu dem "
           "Punkt, wo wir jetzt gerade sind. Klausulnotation Am besten! Mit einer "
           "F1-B-5-9-105-1015 2019 Polski Der Konflikt L conflicts des Klausulnotation "
           "Kurv für das Klausulnotation Klausulnotation Dr Klausulnotation "
           "Klausulnotation Vergnügen")
    cleaned, dropped = strip_hallucinated_tail(raw)
    assert "Polski" not in cleaned and "conflicts" not in cleaned
    assert "Polski" in dropped
    # Der echte Anfang bleibt unangetastet.
    assert cleaned.startswith("Aber ja, da weiß ich wohl der Fehler")
    assert "wo wir jetzt gerade sind." in cleaned


def test_hallucination_guard_spares_real_speech():
    """Die Laengenbedingung ist der Schutz — alle drei Faelle stehen so im Log.

    Kurze Fuell-/Funktionswoerter haeuft echtes Sprechen sehr wohl. Ohne die
    Mindestwortlaenge wuerde der Guard hier zuschlagen und Gesagtes loeschen —
    besonders schlimm beim Mathe-Diktat, wo "minus" naturgemaess dicht steht.
    """
    from fleech.textfilter import strip_hallucinated_tail

    echt = [
        # Mathematik: "minus" 4x in einem Satz — voellig normal.
        "Wir haben das als eine Nullstelle und dann müssen wir noch die Determinante "
        "von t minus 1, minus 2, minus 2 und t minus 1 bestimmen, also von der Matrix.",
        # Rhetorische Wiederholung kurzer Woerter.
        "Ich glaube über alte würde ja auch gehen, das macht ja sonst eigentlich auch "
        "nicht so viel, dann gerne vorschlagen, gerne implementieren, gerne "
        "eigenständig weiterentwickeln.",
        "Fände ich zwar gut, aber da bin ich skeptisch. Da bin ich sehr, sehr, sehr "
        "skeptisch, ob wir das überhaupt dürfen.",
    ]
    for text in echt:
        cleaned, dropped = strip_hallucinated_tail(text)
        assert dropped == "", f"faelschlich verworfen: {dropped!r}"
        assert cleaned == text


def test_hallucinated_tail_never_reaches_the_model():
    """Der Guard laeuft VOR dem LLM und meldet die Loeschung.

    Beides ist wesentlich: Bekaeme das Modell den Ausschuss zu sehen, baute es ihn
    beim Bereinigen in einen plausiblen Satz ein — genau das Fehlerbild, das
    gemeldet wurde. Und `last_dropped_tail` traegt die Warnung in die Pille;
    stillschweigend loeschen darf Fleech nichts.
    """
    raw = ("Kannst du das in meiner Datei einmal korrigieren? Am besten in perfekter "
           "Klausulnotation zu dem Punkt, wo wir jetzt gerade sind. Klausulnotation "
           "Am besten! Mit einer F1-B-5 2019 Polski Der Konflikt L conflicts des "
           "Klausulnotation Kurv für das Klausulnotation Klausulnotation Dr "
           "Klausulnotation Klausulnotation Vergnügen")
    p, llm, injector = make_pipeline(raw)
    p.process(AUDIO, 16000)

    _system, user_text = llm.calls[0]
    assert "Polski" not in user_text and "conflicts" not in user_text
    assert "wo wir jetzt gerade sind." in user_text
    assert "Polski" in p.last_dropped_tail


def test_clean_dictation_reports_no_dropped_tail():
    """Kein Fehlalarm-Kanal: Ohne Halluzination bleibt die Warnung leer."""
    p, _llm, _injector = make_pipeline(
        "Das ist ein ganz normales Diktat ohne jede Wiederholung am Ende."
    )
    p.process(AUDIO, 16000)
    assert p.last_dropped_tail == ""


def test_hallucination_guard_keeps_short_dictation_whole():
    """Bleibt zu wenig echter Text stehen, wird NICHT geschnitten — dann ist das
    ganze Diktat Ausschuss und der Nutzer soll das sehen statt einen Rest."""
    from fleech.textfilter import strip_hallucinated_tail

    cleaned, dropped = strip_hallucinated_tail("Klausulnotation " * 9)
    assert dropped == ""
    assert cleaned.startswith("Klausulnotation")


def test_fremdsprachiger_schwanz_wird_verworfen():
    """Der real gemeldete Fall: Nach dem Diktat lief Musik weiter, Whisper machte
    daraus mehrsprachigen Wortsalat. Kein Guard griff — keine Wiederholung, kein
    dominantes Wort. Der sichere Marker ist die fremde SCHRIFT: Kyrillisch oder
    Koreanisch in einem deutschen Diktat kann nur geraten sein.
    """
    from fleech.textfilter import strip_foreign_tail

    raw = ("Analysiere das dir vorliegende Plugin. Es ist ein Minecraft-Bot, der auf "
           "einem Server läuft. Gib mir praxisnahe Anweisungen, was ich zu tun habe. "
           "Wie teste ich das? Und so weiter und so fort. "
           "Und jetzt Porque dice War, war es ein bisschen Nähan. "
           "Denn Sie ладно, da sind schon mal ein bisschen más schnell.")
    cleaned, dropped = strip_foreign_tail(raw)

    assert "ладно" not in cleaned
    assert "ладно" in dropped
    assert cleaned.startswith("Analysiere das dir vorliegende Plugin.")
    assert "Und so weiter und so fort." in cleaned


def test_griechische_buchstaben_bleiben_unangetastet():
    """DIE Fehlalarm-Gefahr: α, β und λ stehen regelmäßig in Formeln. Griechisch
    ist deshalb bewusst NICHT in der Zeichenliste — ein Mathe-Diktat darf nie
    beschnitten werden."""
    from fleech.textfilter import strip_foreign_tail

    for text in (
        "Die Ableitung von e hoch λ x ist λ mal e hoch λ x, das gilt für alle x.",
        "Sei α der Winkel und β die Gegenkathete, dann folgt daraus der Sinussatz.",
        "Das Integral über φ von 0 bis 2π ergibt genau den Umfang des Kreises.",
    ):
        cleaned, dropped = strip_foreign_tail(text)
        assert dropped == "", f"faelschlich verworfen: {dropped!r}"
        assert cleaned == text


def test_fremdschrift_schneidet_nicht_wenn_zu_wenig_bleibt():
    """Ist praktisch das ganze Diktat Ausschuss, wird NICHT beschnitten — dann soll
    der Nutzer sehen, was passiert ist, statt einen sinnlosen Rest zu bekommen."""
    from fleech.textfilter import strip_foreign_tail

    cleaned, dropped = strip_foreign_tail("Кто это ладно 진짜 was")
    assert dropped == ""
    assert cleaned.startswith("Кто")


def test_pipeline_verwirft_fremdschrift_vor_dem_modell():
    """Der Ausschuss darf das LLM nie erreichen — sonst baut es ihn in einen
    plausiblen Satz ein. Und die Loeschung wird gemeldet."""
    raw = ("Analysiere bitte das Plugin und gib mir danach eine Schritt für Schritt "
           "Anleitung dazu. Wie teste ich das? Und so weiter und so fort. "
           "Denn Sie ладно, da sind schon mal ein bisschen más schnell.")
    p, llm, _injector = make_pipeline(raw)
    p.process(AUDIO, 16000)

    _system, user_text = llm.calls[0]
    assert "ладно" not in user_text
    assert "Und so weiter und so fort." in user_text
    assert "ладно" in p.last_dropped_tail


def test_verlorene_verneinung_wird_erkannt():
    """Die Lücke aus dem Gutachten: Das Modell dreht die AUSSAGE, ohne fremde Wörter
    einzuführen. Wortüberlappung und Wortgetreue bleiben hoch — alle bisherigen
    Schichten sind blind dafür."""
    from fleech.textfilter import meaning_flipped

    raw = "die miete ist im januar noch nicht überwiesen"
    assert meaning_flipped(raw, "Die Miete ist im Januar noch nicht überwiesen.") == ""
    assert "Verneinung" in meaning_flipped(raw, "Die Miete ist im Januar überwiesen.")


def test_verlorene_zahl_wird_erkannt():
    """Real aus dem Verlauf: „Heute ist der 6.7." wurde zu „der 6., oder der 7.?" —
    und in einem anderen Diktat verschwanden zwei Geldbeträge ersatzlos."""
    from fleech.textfilter import meaning_flipped

    raw = "die rechnung über 22,60 euro ist noch offen"
    assert meaning_flipped(raw, "Die Rechnung über 22,60 Euro ist noch offen.") == ""
    treffer = meaning_flipped(raw, "Die Rechnung ist noch offen.")
    assert "22,60" in treffer


def test_selbstkorrektur_darf_die_verneinung_verlieren():
    """Wer sich korrigiert, nimmt die Verneinung selbst zurück — das ist richtig so
    und darf keinen Fehlalarm auslösen."""
    raw = ("wir treffen uns nicht am montag ach nein warte doch wir treffen uns "
           "am montag um drei")
    llm = FakeLLM(reply="Wir treffen uns am Montag um drei.")
    p, _llm, injector = make_pipeline(raw, llm=llm)

    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == ["Wir treffen uns am Montag um drei."]
    assert len(llm.calls) == 1                      # kein Zweitversuch


def test_gedrehte_aussage_loest_zweitversuch_aus():
    """Erst ein Zweitversuch mit Ansage — erst wenn auch der die Aussage dreht,
    gewinnt das Roh-Transkript."""
    raw = "der server ist seit gestern nicht mehr erreichbar gewesen"
    replies = iter(["Der Server ist seit gestern erreichbar gewesen.",
                    "Der Server ist seit gestern nicht mehr erreichbar gewesen."])
    llm = FakeLLM(reply="")
    llm.complete = lambda s, u: (llm.calls.append((s, u)), next(replies))[1]
    p, _llm, injector = make_pipeline(raw, llm=llm)

    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == ["Der Server ist seit gestern nicht mehr erreichbar gewesen."]
    assert len(llm.calls) == 2


def test_hartnaeckig_gedrehte_aussage_faellt_auf_rohtext():
    raw = "die zahlung ist nicht eingegangen und wir warten weiterhin darauf"
    llm = FakeLLM(reply="Die Zahlung ist eingegangen und wir warten weiterhin darauf.")
    p, _llm, injector = make_pipeline(raw, llm=llm)

    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [raw]
