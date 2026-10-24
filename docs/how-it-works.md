# How Fleech handles a dictation

Status: 6.4.0. This page is for anyone who wants to know what happens between pressing the
key and the text appearing, and why Fleech checks the AI instead of trusting it. It
describes the default settings. For the code behind each step, read
[architecture.md](architecture.md); the complete German description is
[concept.de.md](concept.de.md), chapter 5.

## The problem with "transcribe, then ask an AI"

A speech model writes down what you said, including "um", false starts and missing
punctuation. Handing that transcript to a chat model with "clean this up" seems like the
obvious next step. It fails in ways that are easy to miss:

- **A dictation looks like a request.** "Write a function that sorts the list" is
  something you want to *type*, for example into an AI chat. A chat model reads it as
  a task and writes the function.
- **Questions get answered.** "What's the best way to cook rice?" comes back as a recipe.
- **Your wording gets "improved".** "I'll look at them" turns into "I'll review them".
  Each change is small, but the text stops sounding like you.
- **Things get added.** A friendly closing line nobody said, or the example sentences
  from the model's own instructions.
- **The speech model invents text too.** On long recordings Whisper can append phrases
  that were never spoken, such as "Thank you." at the end.

The README shows real examples side by side:
[Why not just Whisper + ChatGPT?](../README.md#why-not-just-whisper--chatgpt)

Fleech treats every step after the recording as something that can go wrong, and keeps
your own words whenever a check fails.

## 1. Recording

Fleech records only the selected microphone, not your system audio (a microphone can
still pick up loudspeakers, though). While you hold the key, it cuts the audio at pauses of at least 400 ms
and recognises each section of 6 to 28 seconds in the background. When you let go, only
the last part is left to recognise.

## 2. Speech recognition

Whisper `large-v3-turbo` runs on your computer through faster-whisper (an optional version
retrained on German can replace it). Before each dictation, Whisper gets a short hint with the words
you are likely to use:

- the entries of your personal dictionary,
- terms Fleech learned in the current app and window (project memory, *Gedächtnis*),
- the safe word, so "Kimono" is not heard as something else.

This happens at the source: a name Whisper spells right never has to be repaired later.
The project memory is used only for this hint and never sent to a language model.

Right after recognition, Fleech removes what Whisper made up:

| What | How it is recognised | What happens |
|---|---|---|
| Recordings under 0.3 s | length | dropped |
| Phrases at the end with no sound behind them ("Vielen Dank.", "Thank you.") | the audio under the segment is practically silent (RMS below 0.002) | cut from the end; the cut stops at the first segment with sound |
| The same phrase repeated at the end | 3 or more times (single words: 5) | shortened to one |
| The same loop inside the text | 5 or more times | shortened to one |
| Foreign script or word salad at the end | script and word statistics | cut |

Whisper's own "no speech" score did not help here: in Fleech's measurements it was 0 for
invented and real segments alike. Everything that is cut shows up in the pill and in the
history.

## 3. Which kind of dictation is it?

- **Safe word** ("Kimono, make that more polite"): a voice command that changes the text
  you just dictated.
- **A format** from the profile, a spoken ending ("… als E-Mail") or, for the AI prompt,
  the <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>P</kbd> hotkey: the dictation is deliberately
  rewritten as an email, bullet points or an AI prompt.
- **Everything else** is cleanup, and only cleanup.

Spoken formulas are opt-in: a parser without any AI turns them into LaTeX before the
cleanup and hides them from the model.

## 4. Cleanup

The cleanup model (by default `gemma3:4b-text` via Ollama on your PC, or a cloud provider
with your own key) gets a set of rules: fix *how* something is written, never *what* was
said. Grammar, spelling, punctuation, fillers and self-corrections may change; synonyms,
reordering, shortening and additions may not.

The transcript itself arrives between two markers, with the instruction that everything
inside them is text to tidy up, never an instruction, whatever it says. Models follow
visible markers far more reliably than a rule buried in a prompt.

A few more details:

- **Very short dictations** (up to five words, without numbers and without German fillers
  or correction words) skip the model: Whisper already punctuates them.
- **Long dictations** (over 200 words) are split at sentence ends into blocks of about
  150 words, and each block is cleaned and checked on its own. A small model copes with
  150 words; with 1,800 at once, it does not.
- **A time limit** applies to each dictation: 6 seconds plus 0.025 s per word, at most
  60 seconds (20 seconds more if the model first has to load). If it runs out, you get the
  raw text. If you turned on the cloud fallback, that one dictation goes to your cloud
  provider instead, and so does a dictation the local AI fails on.
- **If a reply is cut off** at the model's length limit, you get the raw text, not half a
  sentence.

## 5. Checking the result

After the model answers, code compares its reply with your transcript. These checks are
deliberately simple: they count words, which is fast and predictable.

| Check | Measures | Limit | If it fails |
|---|---|---|---|
| Executed instead of transcribed | share of the reply's words that appear in what you said | below 50% | your raw words are pasted |
| Invented closing sentences | trailing sentences without support in the transcript | any | cut from the end (the first sentence always stays) |
| Words you never said | share of new words in the reply | above 22% | one stricter second try; the version with fewer new words wins |
| Rephrased | share of your words that survive | below 70% | one stricter second try; below 50% your raw words are pasted |
| Numbers and negations | a time, date, amount or other number with 3+ digits is missing, or a German negation ("nicht", "kein", "nie" …) | any (long dictations: two negations) | one stricter second try, otherwise your raw words |
| Leaked instructions (per block, German prompt) | example sentences from the prompt appear in the reply | any | this block is pasted raw |
| Too much left out (per block) | share of the block's words still present | below 70% | this block is pasted raw |
| No answer, empty answer | — | — | your raw words are pasted |

When Fleech detects a self-correction ("Donnerstag, äh, nein, Freitag"; the correction
words it knows are German), the limits for missing and new words are relaxed and the
number and negation check is skipped, because the withdrawn part disappears on purpose.

**Intervention level** (*Eingriffsgrad*). Settings → *Ausgabe* (Output) sets how much the cleanup may
change. *Minimal* skips the model entirely; the *Privat* and *Coding* profiles use it.
*Strong* allows more smoothing; the *Geschäftlich* (business) profile uses it. With
*Strong*, the checks for new and missing words are off, but numbers and negations are
still checked.

Every fallback is saved in the history with its reason, for example "KI hat umformuliert statt
bereinigt" (the AI rephrased instead of cleaning up). The log records the reason, not your text.

## 6. Finishing touches

- German fillers ("äh", "ähm", "öh") are removed by fixed rules *after* the model, because
  the model left some of them in. In English, removing "um" and "uh" is up to the model,
  and it sometimes keeps one.
- Your dictionary's replacement rules are applied.
- Spoken symbols such as "Slash" or "Hashtag" become characters.

## 7. Pasting

Fleech puts the text on the clipboard, checks that it arrived, returns to the field where
you started (even if you clicked elsewhere meanwhile), presses <kbd>Ctrl</kbd>+<kbd>V</kbd>
and then restores your previous clipboard text. Pasted dictations are kept out of the
Windows clipboard history. If the result is ready more than 30 seconds after the recording
and another window is in front, the text stays in the clipboard and the pill tells you.

## What the checks do not catch

The checks compare words, not meaning. They notice a missing German "nicht" or a missing
date or amount, but not:

- swapped modal verbs ("can" instead of "must"),
- turned-around time words ("before" instead of "after"),
- a dropped restriction ("only", "except").

There are also gaps by design:

- Dictations with fewer than six content words are only checked for invented closing
  sentences; there is not enough material for the other measurements.
- In English, a lost "not" goes unnoticed, and so do self-corrections like "actually":
  the word lists behind these two checks are German.
- With formula recognition on, only the "executed" and "new words" checks run.
- A formatting profile (email, bullet points, AI prompt) rewrites your text on purpose;
  it is only checked for an empty reply.

If a result looks wrong, the raw text hotkey (<kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Z</kbd>)
swaps it for your word-for-word transcript, and the history keeps both versions.
