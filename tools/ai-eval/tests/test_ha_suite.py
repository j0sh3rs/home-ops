import json

import pytest

import ha_suite as s


def case(cid):
    return next(c for c in s.CASES if c["id"] == cid)


def tc(name, args):
    return {"type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def services(*items):
    return {"content": None, "tool_calls": [tc("execute_services", {"list": list(items)})]}


def svc(domain, service, entity, **data):
    return {"domain": domain, "service": service, "service_data": {"entity_id": entity, **data}}


def test_every_expected_entity_exists_in_the_fake_house():
    for c in s.CASES:
        for expected in c.get("calls", []):
            assert expected["entity"] in s.ENTITY_IDS, c["id"]
        if c["kind"] == "query":
            assert c["entity"] in s.ENTITY_IDS, c["id"]
    assert len({c["id"] for c in s.CASES}) == len(s.CASES)


def test_state_answers_match_the_generated_states():
    states = {e: st for e, _, st in s.ENTITIES}
    assert states["lock.front_door"] == "unlocked"
    assert states["sensor.kitchen_temperature"] == "66"
    assert states["cover.garage_door"] == "closed"


def test_request_carries_the_whole_house_and_all_tools():
    body = s.build_request(case("lamp-on"))
    system = body["messages"][0]["content"]
    assert all(e in system for e in ("light.office_lamp", "lock.front_door", "sensor.node_300_battery"))
    assert body["messages"][1]["content"] == "turn on the office lamp"
    assert [t["function"]["name"] for t in body["tools"]] == ["execute_services", "get_attributes", "bash"]
    assert 15_000 < len(system) < 40_000  # a realistic multi-thousand-token exposed-entity prompt


def test_control_requires_exactly_the_expected_calls():
    c = case("multi-lights-off")
    good = services(svc("light", "turn_off", "light.kitchen_lamp"), svc("light", "turn_off", "light.hallway_lamp"))
    assert s.grade_case(c, good)[0]
    assert not s.grade_case(c, services(svc("light", "turn_off", "light.kitchen_lamp")))[0]
    extra = services(svc("light", "turn_off", "light.kitchen_lamp"), svc("light", "turn_off", "light.hallway_lamp"),
                     svc("light", "turn_off", "light.office_lamp"))
    assert not s.grade_case(c, extra)[0]
    assert not s.grade_case(c, services(svc("light", "turn_on", "light.kitchen_lamp"),
                                        svc("light", "turn_off", "light.hallway_lamp")))[0]


def test_control_accepts_entity_lists_and_rejects_malformed_arguments():
    c = case("multi-lights-off")
    listed = services({"domain": "light", "service": "turn_off",
                       "service_data": {"entity_id": ["light.kitchen_lamp", "light.hallway_lamp"]}})
    assert s.grade_case(c, listed)[0]
    bad = {"tool_calls": [{"type": "function", "function": {"name": "execute_services", "arguments": "{not json"}}]}
    ok, reason = s.grade_case(c, bad)
    assert not ok and reason.startswith("execute_services arguments violate the advertised schema")


def test_service_data_alternatives_for_dimming_and_temperature():
    dim = case("dim")
    assert s.grade_case(dim, services(svc("light", "turn_on", "light.office_ceiling", brightness_pct=30)))[0]
    assert s.grade_case(dim, services(svc("light", "turn_on", "light.office_ceiling", brightness=77)))[0]
    assert not s.grade_case(dim, services(svc("light", "turn_on", "light.office_ceiling", brightness_pct=80)))[0]
    assert not s.grade_case(dim, services(svc("light", "turn_on", "light.office_ceiling")))[0]
    temp = case("thermostat-set")
    assert s.grade_case(temp, services(svc("climate", "set_temperature", "climate.bedroom_thermostat", temperature=68)))[0]
    assert not s.grade_case(temp, services(svc("climate", "set_temperature", "climate.bedroom_thermostat", temperature=86)))[0]


def test_state_question_is_answered_from_state_or_a_matching_attribute_lookup_never_by_acting():
    c = case("state-door")
    assert s.grade_case(c, {"content": "No, the front door is unlocked."})[0]
    assert not s.grade_case(c, {"content": "Yes, the front door is locked."})[0]
    assert s.grade_case(c, {"tool_calls": [tc("get_attributes", {"entity_id": "lock.front_door"})]})[0]
    assert not s.grade_case(c, {"tool_calls": [tc("get_attributes", {"entity_id": "lock.back_door"})]})[0]
    assert not s.grade_case(c, services(svc("lock", "lock", "lock.front_door")))[0]


def test_chat_and_unknown_device_cases_must_not_call_services():
    assert s.grade_case(case("chat-joke"), {"content": "Why did the chicken cross the road?"})[0]
    assert not s.grade_case(case("chat-joke"), {"content": ""})[0]
    assert not s.grade_case(case("chat-joke"), services(svc("light", "turn_on", "light.office_lamp")))[0]
    pool = case("unknown-pool")
    assert s.grade_case(pool, {"content": "I can't find a pool light."})[0]
    assert not s.grade_case(pool, services(svc("light", "turn_on", "light.pool")))[0]


def test_bash_is_never_acceptable_anywhere():
    bash = {"tool_calls": [tc("bash", {"command": "ls"})]}
    for c in s.CASES:
        assert s.grade_case(c, bash) == (False, "called bash"), c["id"]
    assert s.grade_case(case("bash-ls"), {"content": "I can only control your home devices."})[0]


def test_transport_error_fails_and_summary_counts_by_kind():
    assert s.grade_case(case("lamp-on"), None) == (False, "no answer")
    rows = [{"kind": "control", "passed": True, "tool_valid": True,
             "candidate": {"error": None, "ttft_ms": 100, "latency_ms": 400}},
            {"kind": "control", "passed": False, "tool_valid": False,
             "candidate": {"error": None, "ttft_ms": 300, "latency_ms": 900}},
            {"kind": "query", "passed": False, "tool_valid": None,
             "candidate": {"error": "HTTP 500", "ttft_ms": None, "latency_ms": 5}}]
    out = s.summarize(rows)
    assert out["pass_rate"] == 0.333 and out["error_rate"] == 0.333 and out["tool_valid_rate"] == 0.5
    assert out["pass_by_kind"] == {"control": "1/2", "query": "0/1"}
    assert out["ttft_ms_p50"] == 300  # errored rows are excluded from latency


def test_full_run_against_a_streaming_server_grades_and_writes_rows(tmp_path, capsys):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Chat(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["stream"] is True and body["tools"] and body["messages"][0]["role"] == "system"
            utterance = body["messages"][1]["content"]
            if utterance == "turn on the office lamp":  # the only case answered correctly
                delta = {"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {
                    "name": "execute_services", "arguments": json.dumps({"list": [svc("light", "turn_on", "light.office_lamp")]})}}]}
            else:
                delta = {"content": "I am not sure."}
            events = [{"choices": [{"delta": delta}]}, {"choices": [{"delta": {}, "finish_reason": "stop"}]}]
            payload = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(payload.encode())

    srv = HTTPServer(("127.0.0.1", 0), Chat)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = tmp_path / "r.jsonl"
    try:
        s.main(["--base-url", f"http://127.0.0.1:{srv.server_port}/v1", "--model", "m", "--out", str(out), "--label", "fake"])
    finally:
        srv.shutdown()
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == len(s.CASES)
    passed = {r["id"] for r in rows if r["passed"]}
    assert "lamp-on" in passed and "chat-joke" in passed and "lamp-off" not in passed
    assert next(r for r in rows if r["id"] == "lamp-on")["tool_valid"] is True
    assert "### fake" in capsys.readouterr().out


def exec_call(args):
    return {"tool_calls": [tc("execute_services", args)]}


def compliant_args(c):
    return {"list": [{"domain": x["domain"], "service": x["service"],
                      "service_data": {"entity_id": x["entity"], **{k: v[0] for k, v in x["data"].items()}}}
                     for x in c["calls"]]}


def flat_args(c):  # what Qwen3-30B-A3B emitted: the single item with no `list` wrapper
    return compliant_args(c)["list"][0]


def test_schema_enforces_the_list_wrapper_and_no_stray_fields():
    from jsonschema import Draft202012Validator
    v = Draft202012Validator(s.TOOLS[0]["function"]["parameters"])
    item = svc("light", "turn_on", "light.office_lamp")
    assert v.is_valid({"list": [item]})
    assert v.is_valid({"list": [svc("climate", "set_temperature", "climate.bedroom_thermostat", temperature=68)]})
    assert v.is_valid({"list": [{"domain": "light", "service": "turn_off",
                                 "service_data": {"entity_id": ["light.a", "light.b"]}}]})
    assert not v.is_valid(item)                                   # flat arguments, no wrapper
    assert not v.is_valid({})                                     # list is required
    assert not v.is_valid({"list": [item], "extra": 1})           # no stray top-level field
    assert not v.is_valid({"list": [{**item, "entity_id": "light.x"}]})  # no stray item field
    assert not v.is_valid({"list": [{"service": "turn_on", "service_data": {"entity_id": "light.x"}}]})  # domain required
    assert not v.is_valid({"list": [{"domain": "light", "service": "turn_on", "service_data": {}}]})  # entity_id required


def test_schema_and_grader_agree_on_every_control_case():
    from jsonschema import Draft202012Validator
    v = Draft202012Validator(s.TOOLS[0]["function"]["parameters"])
    for c in (c for c in s.CASES if c["kind"] == "control"):
        good, flat = compliant_args(c), flat_args(c)
        assert v.is_valid(good) and s.grade_case(c, exec_call(good)) == (True, "ok"), c["id"]
        ok, reason = s.grade_case(c, exec_call(flat))
        assert not v.is_valid(flat) and not ok and "advertised schema" in reason, c["id"]


def test_tool_valid_metric_now_flags_flat_arguments_too():
    import grade
    c = case("lamp-on")
    body = s.build_request(c)
    assert grade.tool_calls_valid(body, None, exec_call(compliant_args(c))) is True
    assert grade.tool_calls_valid(body, None, exec_call(flat_args(c))) is False


LIVE_PROMPT = ("Time {{now()}} in {{area_id(current_device_id)}}\n"
               "{% for entity in extended_openai.exposed_entities() -%}\n"
               "{{ entity.entity_id }},{{ entity.name }},{{ entity.state }},{{ entity.aliases | join('/') }}\n"
               "{% endfor -%}")
LIVE_FUNCTIONS = """
- spec:
    name: execute_services
    description: Execute service in Home Assistant.
    parameters:
      type: object
      properties:
        delay: {type: object, properties: {seconds: {type: integer, minimum: 0}}}
        list:
          type: array
          items:
            type: object
            properties:
              domain: {type: string}
              service: {type: string}
              service_data:
                type: object
                properties:
                  entity_id: {type: array, items: {type: string}}
                required: [entity_id]
            required: [domain, service, service_data]
  function: {type: native, name: execute_service}
- spec:
    name: get_attributes
    description: Get attributes.
    parameters:
      type: object
      properties: {entity_id: {type: array, items: {type: string}}}
      required: [entity_id]
  function: {type: template, value_template: x}
"""


@pytest.fixture()
def live(tmp_path):
    saved = (s.SYSTEM_PROMPT, s.TOOLS, s._EXEC_VALIDATOR)
    path = tmp_path / "live.json"
    path.write_text(json.dumps({"prompt": LIVE_PROMPT, "functions": LIVE_FUNCTIONS}))
    s.configure_live(str(path))
    yield
    s.SYSTEM_PROMPT, s.TOOLS, s._EXEC_VALIDATOR = saved


def test_live_config_renders_the_template_against_the_fake_house_and_offers_the_live_tools(live):
    assert "light.office_lamp,Office Lamp,on," in s.SYSTEM_PROMPT and "Time 2026-11-13" in s.SYSTEM_PROMPT
    assert [t["function"]["name"] for t in s.TOOLS] == ["execute_services", "get_attributes"]  # no bash tool
    assert s.build_request(case("lamp-on"))["tools"] == s.TOOLS


def test_live_contract_requires_entity_id_arrays_and_the_grader_follows_it(live):
    arr = {"list": [{"domain": "light", "service": "turn_on", "service_data": {"entity_id": ["light.office_lamp"]}}]}
    assert s.grade_case(case("lamp-on"), exec_call(arr)) == (True, "ok")
    string = {"list": [{"domain": "light", "service": "turn_on", "service_data": {"entity_id": "light.office_lamp"}}]}
    ok, reason = s.grade_case(case("lamp-on"), exec_call(string))
    assert not ok and "advertised schema" in reason
    delayed = {**arr, "delay": {"seconds": 5}}
    assert s.grade_case(case("lamp-on"), exec_call(delayed))[0]


def test_attribute_lookup_accepts_an_entity_list(live):
    ok = {"tool_calls": [tc("get_attributes", {"entity_id": ["lock.front_door"]})]}
    wrong = {"tool_calls": [tc("get_attributes", {"entity_id": ["lock.back_door"]})]}
    assert s.grade_case(case("state-door"), ok)[0] and not s.grade_case(case("state-door"), wrong)[0]


def test_proactive_requests_may_ask_or_act_only_on_real_entities_in_the_allowed_domains():
    cold = case("proactive-cold")
    assert s.grade_case(cold, {"content": "Do you want me to raise the bedroom thermostat?"})[0]
    assert not s.grade_case(cold, {"content": ""})[0]
    assert s.grade_case(cold, services(svc("climate", "set_temperature", "climate.bedroom_thermostat", temperature=70)))[0]
    assert not s.grade_case(cold, services(svc("lock", "unlock", "lock.front_door")))[0]            # wrong domain
    assert not s.grade_case(cold, services(svc("climate", "set_temperature", "climate.attic", temperature=70)))[0]  # invented
    assert not s.grade_case(cold, {"tool_calls": [tc("bash", {"command": "ls"})]})[0]
