"""Single-Instance-Lock: verhindert parallele Fleech-Prozesse (Zombie-Bug-Klasse)."""

import sys
import threading
import uuid

import pytest

from fleech.singleinstance import SingleInstanceLock

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-Mutex")


def _name() -> str:
    return f"FleechTest.{uuid.uuid4().hex}"


def test_second_acquire_fails_while_first_holds():
    name = _name()
    first, second = SingleInstanceLock(name), SingleInstanceLock(name)
    try:
        assert first.acquire(retries=0)
        assert first._handle is not None
        assert not second.acquire(retries=0)
        assert second._handle is None
    finally:
        first.release()
        second.release()


def test_release_frees_the_lock():
    name = _name()
    first, second = SingleInstanceLock(name), SingleInstanceLock(name)
    try:
        assert first.acquire(retries=0)
        first.release()
        assert second.acquire(retries=0)
    finally:
        second.release()


def test_different_names_do_not_collide():
    a, b = SingleInstanceLock(_name()), SingleInstanceLock(_name())
    try:
        assert a.acquire(retries=0)
        assert b.acquire(retries=0)
    finally:
        a.release()
        b.release()


def test_retry_covers_reload_window():
    """"Neu laden": alter Prozess gibt den Mutex kurz nach dem Start des neuen frei."""
    name = _name()
    old, new = SingleInstanceLock(name), SingleInstanceLock(name)
    try:
        assert old.acquire(retries=0)
        threading.Timer(0.3, old.release).start()
        assert new.acquire(retries=4, delay=0.2)  # muss durch Retry durchkommen
    finally:
        old.release()
        new.release()
