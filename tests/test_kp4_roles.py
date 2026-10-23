"""KP4 row semantics: hand-written wire examples against both parsers and deck."""

import kp4
import pytest
import test_kp4_core as harness

core = harness.core
deck = harness.deck


def test_hand_written_role_codes_reach_the_committed_snapshot(deck):
    frame = "KP4|A0|0|1|CLAUDE|0|012340|TITLE|OK|NOTICE|WARN|FAIL|"
    ret, parsed = deck.parse(frame)
    assert ret == 0 and parsed == kp4.parse(frame)
    assert parsed.row_roles == (0, 1, 2, 3, 4, 0)
    deck.accept(frame)
    assert deck.snapshot()["row_roles"] == (0, 1, 2, 3, 4, 0)


@pytest.mark.parametrize("roles", ["", "01234", "0123400", "012345", "-12340", "01234x", "012 40"])
def test_malformed_roles_fail_in_both_parsers_and_preserve_visible_deck(deck, roles):
    deck.accept("KP4|A0|0|1|NONE|0|100000|OLD|||||")
    before = deck.snapshot()
    malformed = f"KP4|B0|0|1|NONE|0|{roles}|NEW|||||"
    with pytest.raises(kp4.FrameError):
        kp4.parse(malformed)
    ret, committed = deck.write(malformed)
    assert ret < 0 and not committed
    assert deck.snapshot() == before


def test_old_kp3_frame_is_rejected(deck):
    old = "KP3|A0|0|1|NONE|0|TITLE|||||"
    with pytest.raises(kp4.FrameError):
        kp4.parse(old)
    assert deck.write(old)[0] < 0


def test_roles_stage_atomically_and_survive_staleness_and_navigation(deck):
    deck.accept("KP4|A0|0|1|NONE|0|100000|OLD|||||")
    before = deck.snapshot()
    assert not deck.accept("KP4|B0|0|2|NONE|0|234000|FIRST|||||")
    assert deck.snapshot() == before
    assert deck.accept("KP4|B0|1|2|NONE|0|400001|SECOND|||||")
    assert deck.snapshot()["row_roles"] == (2, 3, 4, 0, 0, 0)
    deck.page_advance(1)
    stale = deck.snapshot(now_ms=360000)
    assert stale["stale"] and stale["row_roles"] == (4, 0, 0, 0, 0, 1)


@pytest.mark.parametrize(
    "roles", [(0,) * 5, (0,) * 7, (0, 0, 0, 0, 0, 5), (False, 0, 0, 0, 0, 0), ("1", 0, 0, 0, 0, 0)]
)
def test_builder_rejects_invalid_semantic_roles(roles):
    with pytest.raises(kp4.FrameError, match="row_roles"):
        kp4.build_frame("NONE", row_roles=roles)
