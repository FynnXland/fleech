"""Die Seiten der Einfuehrung (`ui/onboarding.py`), je Seite ein Modul.

Gleiches Muster wie `ui/settings/`: Eine Seite baut sich mit `build(dialog)` und
legt die Widgets, die der Dialog spaeter braucht, als Attribute auf ihm ab. Die
KI-Seite ist eine eigene Klasse, weil sie Netzarbeit im Hintergrund erledigt.

Ein Teil kennt sein Ganzes nicht: Kein Modul hier importiert `onboarding`.
"""
