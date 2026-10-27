from __future__ import annotations

import httpx

from .client import VikunjaClient

MAX_PER_PAGE = 100


def vikunja_projects(client: VikunjaClient, project_id: int | None = None, search: str | None = None) -> object:
    if project_id is not None:
        return client.get(f"/projects/{project_id}")
    return client.get("/projects", {"s": search})


def vikunja_tasks(client: VikunjaClient, project_id: int | None = None, search: str | None = None,
                  filter: str | None = None, page: int = 1, per_page: int = 50) -> object:
    params = {"s": search, "filter": filter, "page": max(page, 1), "per_page": min(max(per_page, 1), MAX_PER_PAGE)}
    if project_id is not None:
        return client.get(f"/projects/{project_id}/tasks", params)
    try:
        return client.get("/tasks", params)
    except httpx.HTTPStatusError as e:  # Vikunja < 0.24 calls it /tasks/all
        if e.response.status_code not in (404, 405):
            raise
        return client.get("/tasks/all", params)


def vikunja_task(client: VikunjaClient, task_id: int) -> object:
    return client.get(f"/tasks/{task_id}")


def vikunja_create_task(client: VikunjaClient, project_id: int, title: str, description: str | None = None,
                        due_date: str | None = None, priority: int | None = None) -> object:
    if not title.strip():
        raise ValueError("title must not be empty")
    body = {"title": title, "description": description, "due_date": due_date, "priority": priority}
    return client.put(f"/projects/{project_id}/tasks", {k: v for k, v in body.items() if v is not None})


def vikunja_update_task(client: VikunjaClient, task_id: int, title: str | None = None,
                        description: str | None = None, due_date: str | None = None,
                        priority: int | None = None, done: bool | None = None) -> object:
    # POST /tasks/{id} replaces the task and zeroes omitted fields, so merge into the current one
    task = client.get(f"/tasks/{task_id}")
    changes = {"title": title, "description": description, "due_date": due_date, "priority": priority, "done": done}
    task.update({k: v for k, v in changes.items() if v is not None})
    return client.post(f"/tasks/{task_id}", task)


def vikunja_comments(client: VikunjaClient, task_id: int) -> object:
    return client.get(f"/tasks/{task_id}/comments")


def vikunja_add_comment(client: VikunjaClient, task_id: int, comment: str) -> object:
    if not comment.strip():
        raise ValueError("comment must not be empty")
    return client.put(f"/tasks/{task_id}/comments", {"comment": comment})


def vikunja_labels(client: VikunjaClient, search: str | None = None) -> object:
    return client.get("/labels", {"s": search})


def vikunja_add_label(client: VikunjaClient, task_id: int, label_id: int) -> object:
    return client.put(f"/tasks/{task_id}/labels", {"label_id": label_id})
