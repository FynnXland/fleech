# Third-party components

Fleech's own source code is licensed under the [MIT License](LICENSE). The Windows
installer and the Linux binary also bundle the libraries below. They keep their own licenses; nothing in
Fleech's license changes their terms.

| Component | License | Source |
|---|---|---|
| PySide6 / Shiboken6 / Qt 6 | LGPL-3.0 | https://code.qt.io/cgit/pyside/pyside-setup.git |
| pynput | LGPL-3.0 | https://github.com/moses-palmer/pynput |
| faster-whisper | MIT | https://github.com/SYSTRAN/faster-whisper |
| CTranslate2 | MIT | https://github.com/OpenNMT/CTranslate2 |
| PyAV (bundles FFmpeg libraries) | BSD-3-Clause; FFmpeg: LGPL-2.1-or-later | https://github.com/PyAV-Org/PyAV |
| tokenizers, huggingface_hub | Apache-2.0 | https://github.com/huggingface |
| onnxruntime | MIT | https://github.com/microsoft/onnxruntime |
| NumPy | BSD-3-Clause (and others, see package) | https://numpy.org |
| sounddevice | MIT | https://github.com/spatialaudio/python-sounddevice |
| keyring | MIT | https://github.com/jaraco/keyring |
| sqlcipher3-wheels (bundles SQLCipher and OpenSSL 3) | zlib; SQLCipher: BSD-3-Clause; OpenSSL: Apache-2.0 | https://github.com/laggykiller/sqlcipher3 |
| cryptography | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| PyYAML | MIT | https://github.com/yaml/pyyaml |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| pyperclip | BSD-3-Clause | https://github.com/asweigart/pyperclip |
| Pillow | MIT-CMU | https://github.com/python-pillow/Pillow |
| pycaw, comtypes (Windows) | MIT | https://github.com/AndreMiras/pycaw |
| pulsectl, copykitten, python-xlib (Linux) | MIT / LGPL-2.1 (python-xlib) | see each package |
| NVIDIA cuBLAS / cuDNN (GPU build) | NVIDIA Software License (redistributable) | https://developer.nvidia.com |

The LGPL-licensed libraries are shipped as separate, unmodified shared libraries and
Python packages. You may replace them with your own builds of the same version; their
complete source code is available at the links above.

## Models

Speech and language models are not part of Fleech's installer or source. The setup
downloads them onto your computer; they keep their publishers' own licenses and terms.

| Model | Used for | License / terms | Source |
|---|---|---|---|
| Whisper large-v3-turbo (CTranslate2 conversion) | Speech recognition (default) | MIT | https://huggingface.co/openai/whisper-large-v3-turbo, conversion: https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo |
| Whisper large-v3-turbo German (primeline, CTranslate2 conversion) | Speech recognition, optional German model | Apache-2.0 | https://huggingface.co/primeline/whisper-large-v3-turbo-german, conversion: https://huggingface.co/jimmymeister/whisper-large-v3-turbo-german-ct2 |
| Gemma 3 (`gemma3:4b`, default AI model) | Clean-up, output formats, translation | [Gemma Terms of Use](https://ai.google.dev/gemma/terms) and [Gemma Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy) | https://ollama.com/library/gemma3 |
| Ollama | Runs the local AI model | MIT | https://github.com/ollama/ollama |

Gemma is provided under and subject to the Gemma Terms of Use found at
https://ai.google.dev/gemma/terms. Fleech builds `gemma3:4b-text` on your computer from
the downloaded `gemma3:4b` by leaving out its image part; the text weights are unchanged
and nothing is redistributed. Using Gemma through Fleech means accepting these terms.

Other local models you pick in the settings and cloud models you use with your own key
are under their publishers' licenses and terms.
