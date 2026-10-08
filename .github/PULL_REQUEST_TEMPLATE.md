## What and why

<!-- What does this change, and which problem does it solve? Link the issue: "Fixes #123". -->

## What changes for the user

<!-- One or two sentences for the CHANGELOG, written for someone who uses Fleech,
     not for someone who reads the code. "Nothing visible" is a valid answer. -->

## How it was tested

<!-- Platform (Windows 11 / Linux X11), the pytest result, manual checks.
     Prompt or LLM changes: which local Ollama model you checked live.
     UI changes: a screenshot with sample data. -->

## Checklist

- [ ] New or changed behaviour is covered by tests
- [ ] The full suite passes: `python -m pytest -q`
- [ ] No real dictations, logs, keys, user names or local paths in code, tests or screenshots
- [ ] New code sits in the module where it belongs; no size limit in `tests/test_ui_struktur.py` or `tests/test_kernstruktur.py` was raised
- [ ] Platform-specific code stays behind the existing seams (`platformpaths`, `clipboard`, `audiofocus`, …)
- [ ] A new dependency is listed in `THIRD-PARTY-NOTICES.md` and its license is compatible with MIT
- [ ] I agree that this contribution is licensed under the [MIT License](https://github.com/FynnXland/fleech/blob/main/LICENSE)
