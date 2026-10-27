import asyncio

import httpx

from vikunja_mcp import tools as t
from vikunja_mcp.server import mcp

EXPECTED_TOOLS = {
    "vikunja_projects", "vikunja_tasks", "vikunja_task", "vikunja_comments", "vikunja_labels",
    "vikunja_create_task", "vikunja_update_task", "vikunja_add_comment", "vikunja_add_label",
}


class Fake:
    """Records calls; get() returns canned task data and 404s on /tasks to exercise the fallback."""

    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(("get", path))
        if path == "/tasks":
            raise httpx.HTTPStatusError("x", request=httpx.Request("GET", "http://x"),
                                        response=httpx.Response(404))
        return {"id": 7, "title": "old", "description": "keep", "done": False}

    def post(self, path, body=None):
        self.calls.append(("post", path, body))
        return body

    def put(self, path, body=None):
        self.calls.append(("put", path, body))
        return body


def test_tools_registered():
    assert {x.name for x in asyncio.run(mcp.list_tools())} == EXPECTED_TOOLS


def test_update_keeps_omitted_fields():
    f = Fake()
    out = t.vikunja_update_task(f, 7, done=True)
    assert out == {"id": 7, "title": "old", "description": "keep", "done": True}, out


def test_all_tasks_falls_back_to_legacy_route():
    f = Fake()
    t.vikunja_tasks(f, per_page=9999)
    assert ("get", "/tasks/all") in f.calls


def test_empty_title_rejected():
    try:
        t.vikunja_create_task(Fake(), 1, " ")
    except ValueError:
        return
    raise AssertionError


if __name__ == "__main__":
    test_tools_registered()
    test_update_keeps_omitted_fields()
    test_all_tasks_falls_back_to_legacy_route()
    test_empty_title_rejected()
    print("ok")
