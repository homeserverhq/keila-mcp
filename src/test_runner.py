"""
End-to-end test harness for Keila MCP Server.

Unconditional orchestration: the same sequence of tool calls runs on every
run, threaded through the run store. No test-skipping, no conditional
cleanups, no synthetic "nonexistent" parameter fallbacks. Exception handling
is confined to defensive payload parsing in helper utilities only.
"""

import asyncio
import datetime
import json
import os
import sys
import time
import uuid
from typing import Any, Callable, Optional

import httpx
from toon_mcp import toon_to_json

MCP_SERVER_PORT = os.environ.get("MCP_SERVER_PORT", "")
API_KEY = os.environ.get("API_KEY", "")
MCP_URL = f"http://localhost:{MCP_SERVER_PORT}/mcp"

MCP_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
}

TEST_SENDER_ID = "nms_weLJnLY5"

rid = uuid.uuid4().hex[:8]

results: list[dict[str, Any]] = []
store: dict[str, Any] = {}
tested_tools: set[str] = set()


class MCPSession:
    def __init__(self, url: str, headers: dict[str, str]):
        self.url = url
        self.base_headers = {
            **headers,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.session_headers = dict(self.base_headers)
        self.client = httpx.AsyncClient(timeout=120.0)
        self._request_id = 0
        self._session_id: str | None = None

    async def __aenter__(self):
        await self._initialize()
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    @staticmethod
    def _parse_sse(body: str) -> list[dict]:
        messages: list[dict] = []
        data_buf: list[str] = []
        for line in body.splitlines():
            if line.startswith("data: "):
                data_buf.append(line[6:])
            elif line.startswith("data:"):
                data_buf.append(line[5:])
            elif line == "" and data_buf:
                try:
                    messages.append(json.loads("".join(data_buf)))
                except json.JSONDecodeError:
                    pass
                data_buf = []
        if data_buf:
            try:
                messages.append(json.loads("".join(data_buf)))
            except json.JSONDecodeError:
                pass
        return messages

    async def _send_notification(self, method: str, params: dict | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        response = await self.client.post(self.url, headers=self.session_headers, json=payload)
        if response.status_code not in (200, 202):
            response.raise_for_status()

    async def _send(self, method: str, params: dict | None = None) -> dict:
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params:
            payload["params"] = params
        response = await self.client.post(self.url, headers=self.session_headers, json=payload)
        if response.status_code == 202:
            return {}
        response.raise_for_status()

        sid = response.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
            self.session_headers = {**self.base_headers, "mcp-session-id": sid}

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            messages = self._parse_sse(response.text)
            data = messages[0] if messages else {}
        else:
            data = response.json()

        if isinstance(data, list):
            data = data[0]
        if isinstance(data, dict) and "error" in data:
            raise Exception(f"JSON-RPC error: {data['error']}")
        return data.get("result", {})

    async def _initialize(self) -> dict:
        result = await self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "keila-test-runner", "version": "1.0"},
        })
        await self._send_notification("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict]:
        result = await self._send("tools/list")
        return result.get("tools", result)

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        params = {"name": name}
        if arguments:
            params["arguments"] = arguments
        return await self._send("tools/call", params)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def is_error(result: dict[str, Any]) -> Optional[str]:
    if "error" in result:
        err = result["error"]
        return err.get("message", str(err))
    if result.get("isError"):
        content = result.get("content", [])
        for c in content:
            if c.get("type") == "text":
                txt = c["text"]
                if txt.startswith("Error calling tool"):
                    return txt.split(":", 1)[1].strip() if ":" in txt else txt
                try:
                    data = json.loads(txt)
                except json.JSONDecodeError:
                    return txt
                if isinstance(data, dict):
                    return data.get("error", txt)
    return None


def extract_content(result: dict[str, Any]) -> Any:
    if result.get("isError"):
        return {}
    content = result.get("content", [])
    for c in content:
        if c.get("type") == "text":
            try:
                return json.loads(c["text"])
            except json.JSONDecodeError:
                return c["text"]
    return result.get("_meta", {})


async def run_test(
    session: MCPSession,
    label: str,
    tool: str,
    params: dict[str, Any] = None,
    verify: Callable[[Any], Optional[str]] = None,
) -> bool:
    if params is None:
        params = {}
    tested_tools.add(tool)
    result = await session.call_tool(tool, params)
    err = is_error(result)
    if err:
        results.append({
            "label": label, "tool": tool, "status": "FAILED",
            "reason": err
        })
        log(f"  FAIL {label}: {err}")
        return False
    data = extract_content(result)
    if verify is not None:
        verr = verify(data)
        if verr:
            results.append({
                "label": label, "tool": tool, "status": "FAILED",
                "reason": f"verify: {verr}"
            })
            log(f"  FAIL {label}: verify: {verr}")
            return False
    results.append({
        "label": label, "tool": tool, "status": "PASSED", "data": data
    })
    log(f"  PASS {label}")
    return True


async def run_expect_error(
    session: MCPSession,
    label: str,
    tool: str,
    params: dict[str, Any] = None,
    must_contain: str = None,
) -> bool:
    if params is None:
        params = {}
    tested_tools.add(tool)
    try:
        result = await session.call_tool(tool, params)
        err = is_error(result)
    except Exception as e:
        err = str(e)
    if err:
        if must_contain and must_contain.lower() not in err.lower():
            results.append({
                "label": label, "tool": tool, "status": "FAILED",
                "reason": f"error did not mention {must_contain!r}: {err}"
            })
            log(f"  FAIL {label}: {err} (missing {must_contain!r})")
            return False
        results.append({
            "label": label, "tool": tool, "status": "PASSED",
            "data": {"expected_error": err}
        })
        log(f"  PASS {label} (expected error)")
        return True
    results.append({
        "label": label, "tool": tool, "status": "FAILED",
        "reason": "expected tool error but call succeeded"
    })
    log(f"  FAIL {label}: expected error but call succeeded")
    return False


async def run_test_with_store(
    session: MCPSession,
    label: str,
    tool: str,
    params: dict[str, Any] = None,
    store_key: str = None,
) -> bool:
    ok = await run_test(session, label, tool, params)
    if ok and store_key:
        for r in results:
            if r["label"] == label and r["status"] == "PASSED":
                store[store_key] = r.get("data")
                break
    return ok


def pick_id(key: str) -> Optional[str]:
    entry = store.get(key, {})
    if isinstance(entry, dict):
        return entry.get("id")
    return None


def make_name(base: str) -> str:
    return f"t{rid}-{base}"


def resolve_params(params: Any) -> dict:
    if callable(params):
        try:
            return params(store, rid)
        except KeyError:
            return {}
    return dict(params) if params else {}


def get_list_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("items", "results", "rows", "tree"):
            if key in data:
                val = data[key]
                if isinstance(val, list):
                    return val
                if isinstance(val, str):
                    try:
                        parsed = toon_to_json(val)
                        if isinstance(parsed, list):
                            return parsed
                        if isinstance(parsed, dict):
                            for inner in ("collectives", "pages", "tags", "data"):
                                if inner in parsed and isinstance(parsed[inner], list):
                                    return parsed[inner]
                    except Exception:
                        pass
        return []
    elif isinstance(data, list):
        return data
    return []


async def run_verify_delete(
    session: MCPSession,
    label: str,
    get_tool: str,
    params: dict[str, Any] = None,
) -> bool:
    if params is None:
        params = {}
    tested_tools.add(get_tool)
    result = await session.call_tool(get_tool, params)
    err = is_error(result)
    if err:
        if "not found" in err.lower():
            results.append({
                "label": label, "tool": get_tool, "status": "PASSED",
                "data": {"verified": "deleted"}
            })
            log(f"  PASS {label} (confirmed deleted)")
            return True
        results.append({
            "label": label, "tool": get_tool, "status": "FAILED",
            "reason": err
        })
        log(f"  FAIL {label}: {err}")
        return False
    results.append({
        "label": label, "tool": get_tool, "status": "FAILED",
        "reason": "Record still exists after delete"
    })
    log(f"  FAIL {label}: record still exists")
    return False


def _is_test_artifact(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    name = name.strip()
    if not name.startswith("t"):
        return False
    dash_pos = name.find("-", 1)
    if dash_pos < 2 or dash_pos > 9:
        return False
    prefix = name[1:dash_pos]
    return bool(prefix) and all(c in "0123456789abcdef" for c in prefix)


LEAK_SCAN_CONFIG = [
    ("contact",  "list_all_contacts",  {}, "id", "email",   "delete_contact_by_id",  {"id_type": "id"}),
    ("campaign", "list_all_campaigns", {}, "id", "subject", "delete_campaign_by_id", {}),
    ("form",     "list_all_forms",     {}, "id", "name",    "delete_form_by_id",     {}),
    ("segment",  "list_all_segments",  {}, "id", "name",    "delete_segment_by_id",  {}),
    ("template", "list_all_templates", {}, "id", "name",    "delete_template_by_id", {}),
]


async def _run_leak_detection(session: MCPSession) -> None:
    for entity_type, list_tool, list_params, id_key, name_key, delete_tool, delete_extra in LEAK_SCAN_CONFIG:
        tested_tools.add(list_tool)
        tested_tools.add(delete_tool)
        label = f"Phase5 leak_scan_{entity_type}"
        result = await session.call_tool(list_tool, list_params or None)
        err = is_error(result)
        if err:
            results.append({
                "label": label, "tool": list_tool, "status": "FAILED",
                "reason": f"leak scan list call failed: {err}"
            })
            log(f"  FAIL {label}: {err}")
            continue
        data = extract_content(result)
        items = get_list_items(data)
        leaks = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            name_val = str(item.get(name_key, "") or "")
            if not _is_test_artifact(name_val):
                continue
            item_id = item.get(id_key)
            if item_id is None:
                continue
            leaks += 1
            leak_label = f"LEAK {entity_type} id={item_id} name={name_val[:40]}"
            results.append({
                "label": leak_label, "tool": delete_tool, "status": "FAILED",
                "reason": f"Leaked {entity_type} found after test run — delete was not called or failed"
            })
            log(f"  FAIL {leak_label}")
            del_params = {id_key: item_id, **delete_extra}
            await session.call_tool(delete_tool, del_params)
            log(f"       => cleaned up {entity_type} {item_id}")

        if leaks == 0:
            results.append({
                "label": label, "tool": list_tool, "status": "PASSED",
                "data": {"leaks": 0}
            })
            log(f"  PASS {label}")


def _verify_field(field: str, expected: str) -> Callable[[Any], Optional[str]]:
    def check(data: Any) -> Optional[str]:
        if isinstance(data, dict) and data.get(field) == expected:
            return None
        return f"{field} != {expected!r}"
    return check


def _verify_email(expected: str) -> Callable[[Any], Optional[str]]:
    def check(data: Any) -> Optional[str]:
        if isinstance(data, dict) and data.get("email") == expected:
            return None
        return f"email != {expected!r}"
    return check


def _verify_data_value(expected: Any) -> Callable[[Any], Optional[str]]:
    def check(data: Any) -> Optional[str]:
        if isinstance(data, dict) and data.get("data") == expected:
            return None
        return f"data != {expected!r}"
    return check


def _verify_scheduled_for(data: Any) -> Optional[str]:
    if isinstance(data, dict) and data.get("scheduled_for"):
        return None
    return "scheduled_for not set on campaign"


RESOURCE_TESTS = [
    {
        "label": "contact",
        "create_tool": "create_contact",
        "create_params": {"email": make_name("Contact@example.com"), "first_name": "Test"},
        "list_tool": "list_all_contacts",
        "get_tool": "get_contact_by_id",
        "update_tool": "update_contact",
        "update_params": {"first_name": "Updated"},
        "delete_tool": "delete_contact_by_id",
        "readback_verify": _verify_field("first_name", "Updated"),
    },
    {
        "label": "campaign",
        "create_tool": "create_campaign",
        "create_params": {"subject": make_name("Campaign"), "settings_type": "text"},
        "list_tool": "list_all_campaigns",
        "get_tool": "get_campaign_by_id",
        "update_tool": "update_campaign",
        "update_params": {"subject": f"Updated {make_name('Campaign')}"},
        "delete_tool": "delete_campaign_by_id",
        "readback_verify": _verify_field("subject", f"Updated {make_name('Campaign')}"),
    },
    {
        "label": "form",
        "create_tool": "create_form",
        "create_params": {
            "name": make_name("Form"),
            "fields": [
                {"field": "email", "required": True, "cast": True},
                {"field": "first_name", "required": True, "type": "string"},
                {"field": "last_name", "required": True, "type": "string", "cast": False},
                {"field": "data", "key": "feedback", "label": "Feedback", "type": "string"},
            ],
        },
        "list_tool": "list_all_forms",
        "get_tool": "get_form_by_id",
        "update_tool": "update_form",
        "update_params": {"name": f"Updated {make_name('Form')}"},
        "delete_tool": "delete_form_by_id",
        "readback_verify": lambda d: None if (
            isinstance(d, dict)
            and d.get("name") == f"Updated {make_name('Form')}"
            and isinstance(d.get("settings"), dict) and len(d["settings"]) > 5
            and isinstance(d.get("fields"), list)
            and {f.get("field") for f in d["fields"]} == {"email", "first_name", "last_name", "data"}
            and all(f.get("cast") is True for f in d["fields"])
        ) else f"readback mismatch (fields not all enabled or missing)",
    },
    {
        "label": "segment",
        "create_tool": "create_segment",
        "create_params": {"name": make_name("Segment"), "filter": {}},
        "list_tool": "list_all_segments",
        "get_tool": "get_segment_by_id",
        "update_tool": "update_segment",
        "update_params": {"name": f"Updated {make_name('Segment')}"},
        "delete_tool": "delete_segment_by_id",
        "readback_verify": _verify_field("name", f"Updated {make_name('Segment')}"),
    },
    {
        "label": "template",
        "create_tool": "create_template",
        "create_params": {"name": make_name("Template"), "type": "text"},
        "list_tool": "list_all_templates",
        "get_tool": "get_template_by_id",
        "update_tool": "update_template",
        "update_params": {"name": f"Updated {make_name('Template')}"},
        "delete_tool": "delete_template_by_id",
        "readback_verify": _verify_field("name", f"Updated {make_name('Template')}"),
    },
]


async def main():
    print(f"# Test Report — Keila MCP Server")
    print(f"\n**Date**: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    print(f"**Server**: {MCP_URL}")
    print(f"**Run ID**: {rid}")
    print()

    async with MCPSession(MCP_URL, MCP_HEADERS) as session:
        # ------------------------------------------------------------------
        # Phase 0: Session Init & Tool Discovery
        # ------------------------------------------------------------------
        log("\n=== Phase 0: Session Init & Tool Discovery ===")
        tools_list = await session.list_tools()
        tool_names = [t["name"] for t in tools_list]
        print(f"**Discovered**: {len(tool_names)} tools")
        log(f"Tools: {', '.join(sorted(tool_names))}")

        # ------------------------------------------------------------------
        # Phase 1: Status & Health
        # ------------------------------------------------------------------
        log("\n=== Phase 1: Status & Health ===")
        await run_test(
            session, "A1 check_server_status", "check_server_status",
            verify=lambda d: None if isinstance(d, dict) and d.get("status") == "connected" else "backend unreachable (status != connected)"
        )

        # ------------------------------------------------------------------
        # Phase 2: List Tools
        # ------------------------------------------------------------------
        log("\n=== Phase 2: List Tools ===")
        for res in RESOURCE_TESTS:
            await run_test(session, f"B2 list_{res['label']}", res["list_tool"])
        await run_test(session, "B2 list_sender", "list_all_senders")

        # ------------------------------------------------------------------
        # Phase 3: Resource CRUD Cycle
        # ------------------------------------------------------------------
        log("\n=== Phase 3: Resource CRUD Cycle ===")
        for res in RESOURCE_TESTS:
            label = res["label"]
            create_tool = res["create_tool"]
            create_params = res["create_params"]
            get_tool = res["get_tool"]
            update_tool = res["update_tool"]
            delete_tool = res["delete_tool"]

            await run_test_with_store(
                session, f"C1 create_{label}", create_tool, create_params,
                store_key=f"create_{label}"
            )
            cid = pick_id(f"create_{label}")

            await run_test_with_store(
                session, f"C2 get_{label}_by_id", get_tool,
                {"id": cid},
                store_key=f"get_{label}"
            )

            gid = pick_id(f"get_{label}") or cid

            upd = dict(res["update_params"])
            upd["id"] = gid
            await run_test(
                session, f"C3 update_{label}", update_tool, upd
            )

            await run_test(
                session, f"C3b readback_{label}", get_tool,
                {"id": gid, "include_all_fields": True},
                verify=res["readback_verify"]
            )

            await run_test(
                session, f"C4 delete_{label}_by_id", delete_tool,
                {"id": gid}
            )

            await run_verify_delete(
                session, f"C5 verify_delete_{label}", get_tool,
                {"id": gid, "include_all_fields": True}
            )

        # ------------------------------------------------------------------
        # Phase 4: Domain-Specific Tools
        # ------------------------------------------------------------------
        log("\n=== Phase 4: Domain-Specific Tools ===")

        # D1/D2: update_contact_data / replace_contact_data — fresh contact
        await run_test_with_store(
            session, "D0 create_for_data_update", "create_contact",
            {"email": make_name("DataUpdate@example.com"), "first_name": "Data"},
            store_key="data_update_contact"
        )
        du_id = pick_id("data_update_contact")

        await run_test(
            session, "D1 update_contact_data", "update_contact_data",
            {"id": du_id, "data": {"city": "Munich"}}
        )
        await run_test(
            session, "D1b readback_data_update", "get_contact_by_id",
            {"id": du_id, "include_all_fields": True},
            verify=_verify_data_value({"city": "Munich"})
        )

        # D2: replace_contact_data
        await run_test(
            session, "D2 replace_contact_data", "replace_contact_data",
            {"id": du_id, "data": {"tags": ["test"]}}
        )
        await run_test(
            session, "D2b readback_replace_data", "get_contact_by_id",
            {"id": du_id, "include_all_fields": True},
            verify=_verify_data_value({"tags": ["test"]})
        )

        await run_test(
            session, "D0z cleanup_data_contact", "delete_contact_by_id",
            {"id": du_id}
        )

        # D3: get_contact_by_id with id_type=email (fresh contact)
        await run_test_with_store(
            session, "D0a create_for_email_get", "create_contact",
            {"email": make_name("ByEmail@example.com"), "first_name": "EmailTest"},
            store_key="email_get_contact"
        )
        eg_id = pick_id("email_get_contact")
        await run_test(
            session, "D3b get_by_email", "get_contact_by_id",
            {"id": make_name("ByEmail@example.com"), "id_type": "email"},
            verify=_verify_email(make_name("ByEmail@example.com"))
        )
        await run_test(
            session, "D0z cleanup_email_contact", "delete_contact_by_id",
            {"id": eg_id}
        )

        # D4: send_campaign — create a fresh campaign and send it
        await run_test_with_store(
            session, "D0b create_for_send", "create_campaign",
            {"subject": make_name("SendCamp"), "settings_type": "text"},
            store_key="send_campaign"
        )
        sc_id = pick_id("send_campaign")
        await run_test(
            session, "D4 send_campaign", "send_campaign",
            {"id": sc_id},
            verify=lambda d: None if isinstance(d, dict) and d.get("delivery_queued") else "delivery_queued != True"
        )
        await run_test(
            session, "D0z cleanup_send_campaign", "delete_campaign_by_id",
            {"id": sc_id}
        )

        # D5: schedule_campaign — create campaign + schedule + readback
        await run_test_with_store(
            session, "D0c create_for_schedule", "create_campaign",
            {"subject": make_name("SchedCamp"), "settings_type": "text"},
            store_key="schedule_campaign"
        )
        sch_id = pick_id("schedule_campaign")
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        await run_test(
            session, "D5 schedule_campaign", "schedule_campaign",
            {"id": sch_id, "scheduled_for": future}
        )
        await run_test(
            session, "D5b readback_schedule", "get_campaign_by_id",
            {"id": sch_id, "include_all_fields": True},
            verify=_verify_scheduled_for
        )
        await run_test(
            session, "D0z cleanup_schedule_campaign", "delete_campaign_by_id",
            {"id": sch_id}
        )

        # D6: submit_form — create form with email field and DOI disabled
        await run_test_with_store(
            session, "D0d create_for_submit", "create_form",
            {"name": make_name("SubmitForm"), "fields": [{"field": "email", "required": True, "cast": True}],
             "settings": {"double_opt_in_required": False}},
            store_key="submit_form"
        )
        sf_id = pick_id("submit_form")
        await run_test(
            session, "D6 submit_form", "submit_form",
            {"id": sf_id, "email": make_name("FormSubmit@example.com")},
            verify=_verify_email(make_name("FormSubmit@example.com"))
        )
        await run_test(
            session, "D0z delete_submit_form", "delete_form_by_id",
            {"id": sf_id}
        )
        # Delete the contact created by submit_form
        await run_test(
            session, "D0z cleanup_submit_contact", "delete_contact_by_id",
            {"id": make_name("FormSubmit@example.com"), "id_type": "email"}
        )

        # D7: render_transactional_message
        await run_test(
            session, "D7 render_transactional_message", "render_transactional_message",
            {"type": "text", "sender_id": TEST_SENDER_ID,
             "recipient_email": "solo@selfhostingbox.com",
             "subject": f"t{rid}-Render", "text_body": "Hello Solo"}
        )

        # D8: send_transactional_message
        await run_test(
            session, "D8 send_transactional_message", "send_transactional_message",
            {"type": "text", "sender_id": TEST_SENDER_ID,
             "recipient_email": "solo@selfhostingbox.com",
             "subject": f"t{rid}-Send", "text_body": "Hello Solo"}
        )

        # ------------------------------------------------------------------
        # Phase 4.5: Rejection Validation (negative tests)
        # ------------------------------------------------------------------
        log("\n=== Phase 4.5: Rejection Validation ===")

        # D9a: create_form rejects invalid field enum
        await run_expect_error(
            session, "D9a create_form invalid field", "create_form",
            {"name": make_name("BadFieldForm"), "fields": [{"field": "city"}]},
            must_contain="email"
        )

        # D9b: create_form rejects data field without key
        await run_expect_error(
            session, "D9b create_form data no key", "create_form",
            {"name": make_name("DataNoKeyForm"), "fields": [{"field": "data"}]},
            must_contain="key"
        )

        # D9c: create_form rejects empty fields
        await run_expect_error(
            session, "D9c create_form empty fields", "create_form",
            {"name": make_name("NoFieldsForm"), "fields": []},
            must_contain="least one"
        )

        # D9d: create_form rejects missing email field
        await run_expect_error(
            session, "D9d create_form no email", "create_form",
            {"name": make_name("NoEmailForm"), "fields": [{"field": "first_name"}]},
            must_contain="email"
        )

        # D10a: create_contact rejects invalid email
        await run_expect_error(
            session, "D10a create_contact bad email", "create_contact",
            {"email": "not-an-email"},
            must_contain="email"
        )

        # D10b: create_contact rejects invalid status
        await run_expect_error(
            session, "D10b create_contact bad status", "create_contact",
            {"email": make_name("BadStatus@example.com"), "status": "bogus"},
            must_contain="bogus"
        )

        # D11a: create_template rejects invalid type
        await run_expect_error(
            session, "D11a create_template bad type", "create_template",
            {"name": make_name("BadTypeTpl"), "type": "bogus"},
            must_contain="bogus"
        )

        # D11b: create_campaign rejects invalid settings_type
        await run_expect_error(
            session, "D11b create_campaign bad settings_type", "create_campaign",
            {"subject": make_name("BadSettings"), "settings_type": "bogus"},
            must_contain="bogus"
        )

        # D12a: create_segment rejects invalid filter operator
        await run_expect_error(
            session, "D12a create_segment bad operator", "create_segment",
            {"name": make_name("BadFilter"), "filter": {"email": {"$bad_op": "x"}}},
            must_contain="$bad_op"
        )

        # D13a: send_transactional_message rejects missing recipient
        await run_expect_error(
            session, "D13a send_message no recipient", "send_transactional_message",
            {"type": "text", "sender_id": TEST_SENDER_ID, "subject": "Test", "text_body": "Hello"},
            must_contain="recipient"
        )

        # D13b: send_transactional_message rejects missing body
        await run_expect_error(
            session, "D13b send_message no body", "send_transactional_message",
            {"type": "text", "sender_id": TEST_SENDER_ID, "recipient_email": "solo@selfhostingbox.com", "subject": "Test"},
            must_contain="text_body"
        )

        # ------------------------------------------------------------------
        # Phase 5: Leak Detection
        # ------------------------------------------------------------------
        log("\n=== Phase 5: Leak Detection ===")
        await _run_leak_detection(session)

        # ------------------------------------------------------------------
        # Phase 6: Coverage Assertion — every discovered tool must be invoked
        # ------------------------------------------------------------------
        log("\n=== Phase 6: Coverage Assertion ===")
        missing = sorted(set(tool_names) - tested_tools)
        if missing:
            for t in missing:
                results.append({
                    "label": f"COVERAGE missing tool {t}",
                    "tool": "coverage_check",
                    "status": "FAILED",
                    "reason": "Discovered via tools/list but never invoked by any test"
                })
                log(f"  FAIL COVERAGE: {t} never invoked")
        else:
            log(f"  PASS COVERAGE: all {len(tool_names)} discovered tools invoked")

        # ------------------------------------------------------------------
        # Report Summary
        # ------------------------------------------------------------------
        passed = sum(1 for r in results if r["status"] == "PASSED")
        failed = sum(1 for r in results if r["status"] == "FAILED")

        print(f"\n## Summary\n")
        print(f"| Status | Count |")
        print(f"|--------|-------|")
        print(f"| PASSED | {passed} |")
        print(f"| FAILED | {failed} |")

        if passed:
            print(f"\n## PASSED ({passed})\n")
            for r in results:
                if r["status"] == "PASSED":
                    print(f"- `{r['tool']}` — {r['label']}")

        if failed:
            print(f"\n## FAILED ({failed})\n")
            for r in results:
                if r["status"] == "FAILED":
                    print(f"### {r['label']}")
                    print(f"- **Error**: {r['reason']}")
                    print()

        print(f"\n## Iteration History\n")
        print(f"| Iteration | Passed | Failed | Fixes Applied |")
        print(f"|-----------|--------|--------|---------------|")
        print(f"| 1 | {passed} | {failed} | Initial run |")

        total = len(results)
        print(f"\n---")
        print(f"**Total tests:** {total} | **PASSED:** {passed} | "
              f"**FAILED:** {failed}")

        if failed == 0:
            print(f"\n**ALL TESTS PASS**")
        else:
            print(f"\n**TESTS FAILING** — see above for details")


if __name__ == "__main__":
    asyncio.run(main())
