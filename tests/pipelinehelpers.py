"""Gemeinsame Attrappen der Pipeline-Tests: STT, LLM, Injector, Fertig-Pipeline.

Liegt neben den Testdateien, damit die fuenf Themen-Dateien dieselbe Pipeline
bauen koennen, ohne den Aufbau zu kopieren.
"""

import numpy as np

from fleech.document import DocumentTracker
from fleech.pipeline import Pipeline


class FakeSTT:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def transcribe(self, audio, samplerate, initial_prompt=None):
        self.prompts.append(initial_prompt)
        return self.text


class FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []
        self.audio_calls = []

    def complete(self, system_prompt, user_text):
        self.calls.append((system_prompt, user_text))
        if self.error:
            raise self.error
        return self.reply

    def complete_with_audio(self, system_prompt, user_text, wav_bytes):
        self.audio_calls.append((system_prompt, user_text, wav_bytes))
        if self.error:
            raise self.error
        return self.reply


class FakeInjector:
    def __init__(self):
        self.injected = []
        self.replacements = []  # (geloeschte_zeichen, neuer_text)

    def inject(self, text):
        self.injected.append(text)

    def replace_tail(self, delete_chars, text):
        self.replacements.append((delete_chars, text))


AUDIO = np.zeros(16000, dtype=np.float32)  # 1 s


RAW_NONTRIVIAL = "also äh das hier ist der rohe text mit ein paar mehr worten"


# Realistische Cleanup-Ausgabe dazu: wortgetreu, nur Fuellwoerter/Interpunktion. Eine
# beziehungslose Fake-Antwort wuerde (zu Recht) den Wortgetreue-Guard ausloesen.
CLEAN_NONTRIVIAL = "Das hier ist der rohe Text mit ein paar mehr Worten."


def make_tracker():
    t = DocumentTracker()
    t._window = 42
    t.sync_window = lambda: None  # Fenster-Logik in Unit-Tests neutralisieren
    return t


def make_pipeline(stt_text, llm=None, command_llm=None, fast_llm=None):
    injector = FakeInjector()
    llm = llm or FakeLLM(reply="sauberer Text.")
    p = Pipeline(
        stt=FakeSTT(stt_text),
        cleanup_llm=llm,
        fast_llm=fast_llm,
        injector=injector,
        cleanup_prompt="SYSTEM",
        trigger_word="Redax",
        command_llm=command_llm,
        command_prompt="COMMAND-SYSTEM",
        tracker=make_tracker(),
    )
    return p, llm, injector
