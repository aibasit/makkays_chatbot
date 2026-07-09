"""Unit tests for the Orchestrator's deterministic wizard-escape detection.

Regression coverage for a real bug found via live testing: an active wizard
session used to force-route every message back into the wizard with no way to
ever exit, and a first attempt at a fix (classifying the message and escaping
on a low-confidence out_of_scope guess) broke legitimate one-word wizard
answers like "power" or "10", since the general classifier has no way to know
those are in-context answers rather than off-topic remarks.
"""

from __future__ import annotations

from app.orchestrator.orchestrator import _looks_like_wizard_escape


def test_short_legitimate_wizard_answers_are_not_escapes() -> None:
    assert _looks_like_wizard_escape("power") is False
    assert _looks_like_wizard_escape("10") is False
    assert _looks_like_wizard_escape("small office in Lahore") is False
    assert _looks_like_wizard_escape("no preference") is False


def test_explicit_human_request_is_an_escape() -> None:
    assert _looks_like_wizard_escape("Can I talk to a human please?") is True
    assert _looks_like_wizard_escape("connect me to an agent") is True


def test_explicit_cancel_keywords_are_an_escape() -> None:
    assert _looks_like_wizard_escape("stop asking me this") is True
    assert _looks_like_wizard_escape("never mind, forget it") is True


def test_roman_urdu_dismissal_is_an_escape() -> None:
    assert _looks_like_wizard_escape("Meri baat tu suno, mujhy koi baat nhi krni tumse. jao dafa ho jao.") is True
    assert _looks_like_wizard_escape("bas mein tumse lkhafa hun... mn baat nhi krta tumse") is True
