"""Notification-Policy: verteilt Rueckmeldungen auf Tray, Overlay, Sound, Toast.

Ebenen (Produktprinzip "ruhige Power-User-App"):
- Tray    = dauerhafter Statuskanal, laeuft IMMER (nie unterdrueckt).
- Overlay = aktiver Arbeitskanal; unter Fokusbedingungen reduziert, nie waehrend
            aktiver Aufnahme unterdrueckt (der Nutzer hat sie selbst ausgeloest).
- Sound   = kurzes lokales Feedback; bei DND/Gaming konfigurierbar leiser/stumm.
- Toast   = NUR seltene, wichtige Ereignisse; Default-Politik: so wenig wie moeglich.

Die Policy ist reine Logik (kein Win32, kein Qt) und vollstaendig unit-testbar.
Der Notifier bindet sie an Tray/Sounds und cached den letzten FocusContext.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .windowsfocus import FocusContext

log = logging.getLogger(__name__)

# Toast-Arten → (Settings-Feld, kritisch?)
TOAST_KINDS = {
    "background_info": ("toast_background_info", False),  # "laeuft im Hintergrund"
    "critical_error": ("toast_critical_always", True),
    "provider_quota": ("toast_provider_quota", False),
    "long_processing": ("toast_long_processing", False),
}

_TOAST_COOLDOWN_S = 90.0  # gleiche Toast-Art nicht oefter — keine Toast-Flut


@dataclass
class SoundDecision:
    allowed: bool
    volume_factor: float = 1.0


class NotificationPolicy:
    """Entscheidet auf Basis von FocusSettings + FocusContext. Zustandslos."""

    def __init__(self, settings):
        self.settings = settings  # usersettings.FocusSettings (live-Referenz)

    # -- Hilfen ------------------------------------------------------------------

    def _gaming_active(self, ctx: FocusContext) -> bool:
        s = self.settings
        if not s.gaming_detection or not ctx.gaming_or_fullscreen:
            return False
        proc = (ctx.foreground_process or "").lower()
        return proc not in {e.strip().lower() for e in s.gaming_exceptions if e.strip()}

    def gaming_active(self, ctx: FocusContext) -> bool:
        """Oeffentlich: Spiel/Vollbild im Vordergrund (respektiert Ausnahmen) —
        auch von der LLM-Warmhaltung genutzt (RAM beim Zocken freigeben)."""
        return self._gaming_active(ctx)

    def _dnd_active(self, ctx: FocusContext) -> bool:
        # None (nicht ermittelbar) behandeln wir konservativ als "kein DND",
        # weil sonst Toasts/Sounds dauerhaft grundlos unterdrueckt wuerden.
        return bool(self.settings.respect_dnd and ctx.dnd)

    # -- Toasts ------------------------------------------------------------------

    def allow_toast(self, kind: str, ctx: FocusContext) -> bool:
        s = self.settings
        field, critical = TOAST_KINDS.get(kind, (None, False))
        if field is None:
            log.warning("Unbekannte Toast-Art %r — unterdrueckt.", kind)
            return False
        if critical:
            # Kritisch: eigener Schalter, setzt sich ueber DND/Gaming/Global hinweg.
            return bool(getattr(s, field))
        if not s.toasts_enabled or not getattr(s, field):
            return False
        if self._dnd_active(ctx):
            return False
        if self._gaming_active(ctx):
            return False
        return True

    # -- Sounds ------------------------------------------------------------------

    def sound_decision(self, ctx: FocusContext) -> SoundDecision:
        s = self.settings
        if self._dnd_active(ctx) and s.dnd_mute_sounds:
            return SoundDecision(allowed=False)
        if self._gaming_active(ctx):
            factor = max(0.0, min(1.0, s.gaming_sound_factor))
            return SoundDecision(allowed=factor > 0, volume_factor=factor)
        return SoundDecision(allowed=True)

    # -- Overlay ------------------------------------------------------------------

    def overlay_override(self, ctx: FocusContext) -> str | None:
        """None = Nutzereinstellung gilt; sonst "activity_only" | "compact" | "hidden"."""
        if self._gaming_active(ctx) and self.settings.gaming_overlay != "unchanged":
            return self.settings.gaming_overlay
        if self._dnd_active(ctx):
            # DND: keine Dauerpraesenz — aber Aufnahme-Feedback bleibt erlaubt.
            return "activity_only"
        return None


class Notifier:
    """Bindet die Policy an Tray + SoundPlayer; cached den letzten FocusContext."""

    def __init__(self, policy: NotificationPolicy, tray, sounds, probe):
        self.policy = policy
        self.tray = tray
        self.sounds = sounds
        self.probe = probe
        self._context = FocusContext()
        self._last_toast: dict[str, float] = {}

    @property
    def context(self) -> FocusContext:
        return self._context

    def refresh(self) -> FocusContext:
        try:
            self._context = self.probe.query()
        except Exception:
            log.debug("Focus-Probe fehlgeschlagen.", exc_info=True)
        return self._context

    def toast(self, kind: str, title: str, message: str, bypass_cooldown: bool = False) -> bool:
        ctx = self.refresh()
        if not self.policy.allow_toast(kind, ctx):
            log.info("Toast unterdrueckt (%s): %s", kind, message)
            return False
        now = time.monotonic()
        if not bypass_cooldown and now - self._last_toast.get(kind, -1e9) < _TOAST_COOLDOWN_S:
            log.info("Toast-Cooldown (%s): %s", kind, message)
            return False
        self._last_toast[kind] = now
        self.tray.notify(title, message)
        # Eigener Akzent-Sound nur fuer wirklich wichtige Events (opt-in).
        _, critical = TOAST_KINDS.get(kind, (None, False))
        if critical and self.policy.settings.notification_sounds:
            self.sounds.play("error")
        return True

    def sound(self, event: str) -> None:
        decision = self.policy.sound_decision(self._context)
        if not decision.allowed:
            return
        self.sounds.play(event, volume_factor=decision.volume_factor)
