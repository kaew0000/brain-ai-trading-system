"""Phase W9: tooltip."""

from world.interaction.models import HoverInfo
from world.interaction.tooltip import build_tooltip_text


def test_tooltip_includes_all_present_fields():
    info = HoverInfo(target_id="bastion", kind="character", status="working",
                      room_info="Risk Department", current_event="risk flagged")
    text = build_tooltip_text(info)
    assert "bastion" in text
    assert "Risk Department" in text
    assert "working" in text
    assert "risk flagged" in text


def test_tooltip_omits_empty_fields():
    info = HoverInfo(target_id="bastion", kind="character")
    text = build_tooltip_text(info)
    assert text == "bastion"
