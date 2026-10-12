import json

import pytest

import ha


def call(name, args):
    return {"type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_load_intents(tmp_path):
    p = tmp_path / "i.yaml"
    p.write_text("- id: a\n  utterance: turn on the lamp\n- id: b\n  utterance: what time is it\n")
    assert [i["id"] for i in ha.load_intents(p)] == ["a", "b"]
    p.write_text("- id: a\n  utterance: x\n- id: a\n  utterance: y\n")
    with pytest.raises(ValueError, match="duplicate"):
        ha.load_intents(p)
    p.write_text("- id: a\n")
    with pytest.raises(ValueError, match="utterance"):
        ha.load_intents(p)


def test_pick_template_and_build_request():
    with_tools = {"model": "gpt", "tools": [{"function": {"name": "execute_services"}}],
                  "messages": [{"role": "system", "content": "S"},
                               {"role": "user", "content": "old"},
                               {"role": "assistant", "content": "older"}]}
    records = [{"request": with_tools}, {"request": {"model": "gpt", "messages": []}}]
    template = ha.pick_template(records)
    assert template is with_tools
    body = ha.build_request(template, "turn on the lamp")
    assert body["messages"] == [{"role": "system", "content": "S"},
                                {"role": "user", "content": "turn on the lamp"}]
    assert body["tools"] == with_tools["tools"]
    assert with_tools["messages"][1]["content"] == "old"  # template not mutated
    with pytest.raises(ValueError):
        ha.pick_template([{"request": {"messages": []}}])


def test_pick_template_uses_newest_ts_not_list_order():
    newest = {"model": "gpt", "tools": [{"function": {"name": "new"}}], "messages": []}
    older = {"model": "gpt", "tools": [{"function": {"name": "old"}}], "messages": []}
    records = [
        {"ts": "2026-10-12T10:00:00Z", "request": newest},
        {"ts": "2026-10-11T10:00:00Z", "request": older},  # last in list, but older
        {"ts": "2026-10-13T10:00:00Z", "request": {"model": "gpt", "messages": []}},  # no tools
    ]
    assert ha.pick_template(records) is newest


def test_dict_and_string_arguments_normalise_equal():
    as_dict = {"tool_calls": [{"function": {"name": "s", "arguments": {"entity_id": "Light.Kitchen "}}}]}
    as_str = {"tool_calls": [{"function": {"name": "s", "arguments": '{"entity_id":"light.kitchen"}'}}]}
    assert ha.normalise_calls(as_dict) == ha.normalise_calls(as_str)
    assert ha.agrees(as_dict, as_str)


def test_unparsable_string_arguments_are_normalised():
    msg = {"tool_calls": [{"function": {"name": "s", "arguments": "  Not JSON  "}}]}
    assert ha.normalise_calls(msg) == [("s", "not json")]


def test_agrees_normalises_case_order_and_whitespace():
    base = {"tool_calls": [call("execute_services", {"entity_id": "Light.Lamp "}), call("b", {})]}
    same = {"tool_calls": [call("b", {}), call("execute_services", {"entity_id": "light.lamp"})]}
    other = {"tool_calls": [call("execute_services", {"entity_id": "light.desk"})]}
    assert ha.agrees(base, same)
    assert not ha.agrees(base, other)
    assert ha.agrees({"content": "It is 3pm"}, {"content": "3 o'clock"})  # both text-only
    assert not ha.agrees({"content": "hi"}, same)
    assert not ha.agrees(base, None)
