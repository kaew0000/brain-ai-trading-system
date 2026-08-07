"""Phase W12: search_index + quick_nav."""
from world.runtime.api import get_world_state
from world.workspace.quick_nav import quick_nav_entries
from world.workspace.search_index import build_search_index, search


def test_index_includes_the_building_entry():
    state = get_world_state()
    idx = build_search_index(state)
    assert any(r.kind == "building" for r in idx)


def test_index_includes_all_sixteen_characters():
    state = get_world_state()
    idx = build_search_index(state)
    assert sum(1 for r in idx if r.kind == "character") == 16


def test_index_includes_all_seventeen_rooms_as_room_and_department():
    state = get_world_state()
    idx = build_search_index(state)
    assert sum(1 for r in idx if r.kind == "room") == 17
    assert sum(1 for r in idx if r.kind == "department") == 17


def test_empty_query_returns_nothing():
    state = get_world_state()
    assert search(state, "") == ()
    assert search(state, "   ") == ()


def test_search_is_case_insensitive():
    state = get_world_state()
    results = search(state, "PRIMUS")
    assert any(r.result_id == "primus" for r in results)


def test_search_matches_on_label_id_or_detail():
    state = get_world_state()
    # 'ceo-tower' is primus's detail (current_room_id) as well as a room id/label
    results = search(state, "ceo-tower")
    kinds = {r.kind for r in results}
    assert "character" in kinds
    assert "room" in kinds


def test_search_kinds_filter_restricts_results():
    state = get_world_state()
    results = search(state, "ceo-tower", kinds=("room",))
    assert all(r.kind == "room" for r in results)


def test_search_no_match_returns_empty():
    state = get_world_state()
    assert search(state, "definitely-not-a-real-thing-xyz") == ()


def test_quick_nav_only_returns_allowed_kinds():
    state = get_world_state()
    results = quick_nav_entries(state, "ceo-tower")
    allowed = {"room", "character", "mission", "notification"}
    assert all(r.kind in allowed for r in results)
    assert "department" not in {r.kind for r in results}


def test_quick_nav_finds_a_character_by_ref():
    state = get_world_state()
    results = quick_nav_entries(state, "primus")
    assert any(r.kind == "character" for r in results)
