from __future__ import annotations

from .client import WoodpeckerClient


def woodpecker_orgs(client: WoodpeckerClient, org_id: int | None = None, full_name: str | None = None) -> object:
    if org_id is not None:
        return client.get(f"/orgs/{org_id}")
    if full_name is not None:
        return client.get(f"/orgs/lookup/{full_name}")
    return client.get("/orgs")


def woodpecker_org_permissions(client: WoodpeckerClient, org_id: int) -> object:
    return client.get(f"/orgs/{org_id}/permissions")


def woodpecker_org_secrets(client: WoodpeckerClient, org_id: int, name: str | None = None) -> object:
    if name is not None:
        return client.get(f"/orgs/{org_id}/secrets/{name}")
    return client.get(f"/orgs/{org_id}/secrets")


def woodpecker_org_registries(client: WoodpeckerClient, org_id: int, name: str | None = None) -> object:
    if name is not None:
        return client.get(f"/orgs/{org_id}/registries/{name}")
    return client.get(f"/orgs/{org_id}/registries")


def woodpecker_repos(client: WoodpeckerClient, repo_id: int | None = None, full_name: str | None = None) -> object:
    if repo_id is not None:
        return client.get(f"/repos/{repo_id}")
    if full_name is not None:
        return client.get(f"/repos/lookup/{full_name}")
    return client.get("/repos")


def woodpecker_repo_branches(client: WoodpeckerClient, repo_id: int) -> object:
    return client.get(f"/repos/{repo_id}/branches")


def woodpecker_repo_permissions(client: WoodpeckerClient, repo_id: int) -> object:
    return client.get(f"/repos/{repo_id}/permissions")


def woodpecker_repo_pull_requests(client: WoodpeckerClient, repo_id: int) -> object:
    return client.get(f"/repos/{repo_id}/pull_requests")


def woodpecker_repo_secrets(client: WoodpeckerClient, repo_id: int, name: str | None = None) -> object:
    if name is not None:
        return client.get(f"/repos/{repo_id}/secrets/{name}")
    return client.get(f"/repos/{repo_id}/secrets")


def woodpecker_repo_registries(client: WoodpeckerClient, repo_id: int, name: str | None = None) -> object:
    if name is not None:
        return client.get(f"/repos/{repo_id}/registries/{name}")
    return client.get(f"/repos/{repo_id}/registries")


def woodpecker_repo_cron(client: WoodpeckerClient, repo_id: int, cron_name: str | None = None) -> object:
    if cron_name is not None:
        return client.get(f"/repos/{repo_id}/cron/{cron_name}")
    return client.get(f"/repos/{repo_id}/cron")


def woodpecker_pipelines(client: WoodpeckerClient, repo_id: int, pipeline_number: int | None = None) -> object:
    if pipeline_number is not None:
        return client.get(f"/repos/{repo_id}/pipelines/{pipeline_number}")
    return client.get(f"/repos/{repo_id}/pipelines")


def woodpecker_pipeline_config(client: WoodpeckerClient, repo_id: int, pipeline_number: int) -> object:
    return client.get(f"/repos/{repo_id}/pipelines/{pipeline_number}/config")


def woodpecker_pipeline_metadata(client: WoodpeckerClient, repo_id: int, pipeline_number: int) -> object:
    return client.get(f"/repos/{repo_id}/pipelines/{pipeline_number}/metadata")


def woodpecker_pipeline_logs(client: WoodpeckerClient, repo_id: int, pipeline_number: int, step_id: int) -> object:
    return client.get(f"/repos/{repo_id}/logs/{pipeline_number}/{step_id}")


def woodpecker_queue_pipelines(client: WoodpeckerClient) -> object:
    return client.get("/pipelines")


def woodpecker_queue_info(client: WoodpeckerClient) -> object:
    return client.get("/queue/info")


def woodpecker_secrets(client: WoodpeckerClient, name: str | None = None) -> object:
    if name is not None:
        return client.get(f"/secrets/{name}")
    return client.get("/secrets")


def woodpecker_registries(client: WoodpeckerClient, name: str | None = None) -> object:
    if name is not None:
        return client.get(f"/registries/{name}")
    return client.get("/registries")


def woodpecker_agents(client: WoodpeckerClient, agent_id: int | None = None, org_id: int | None = None) -> object:
    if agent_id is not None:
        return client.get(f"/agents/{agent_id}")
    if org_id is not None:
        return client.get(f"/orgs/{org_id}/agents")
    return client.get("/agents")


def woodpecker_agent_tasks(client: WoodpeckerClient, agent_id: int) -> object:
    return client.get(f"/agents/{agent_id}/tasks")


def woodpecker_forges(client: WoodpeckerClient, forge_id: int | None = None) -> object:
    if forge_id is not None:
        return client.get(f"/forges/{forge_id}")
    return client.get("/forges")


def woodpecker_users(client: WoodpeckerClient, login: str | None = None) -> object:
    if login is not None:
        return client.get(f"/users/{login}")
    return client.get("/users")


def woodpecker_user_self(client: WoodpeckerClient) -> object:
    return client.get("/user")


def woodpecker_user_feed(client: WoodpeckerClient) -> object:
    return client.get("/user/feed")


def woodpecker_user_repos(client: WoodpeckerClient) -> object:
    return client.get("/user/repos")


def woodpecker_server_info(client: WoodpeckerClient) -> dict:
    return {
        "version": client.get("/version"),
        "healthz": client.get("/healthz"),
        "signature_public_key": client.get("/signature/public-key"),
    }


def woodpecker_create_org_secret(
    client: WoodpeckerClient,
    org_id: int,
    name: str,
    value: str,
    events: list[str] | None = None,
    images: list[str] | None = None,
    note: str | None = None,
) -> object:
    body = {"name": name, "value": value}
    if events is not None:
        body["events"] = events
    if images is not None:
        body["images"] = images
    if note is not None:
        body["note"] = note
    return client.post(f"/orgs/{org_id}/secrets", body)


def woodpecker_trigger_pipeline(
    client: WoodpeckerClient,
    repo_id: int,
    branch: str | None = None,
    variables: dict[str, str] | None = None,
) -> object:
    body = {}
    if branch is not None:
        body["branch"] = branch
    if variables is not None:
        body["variables"] = variables
    return client.post(f"/repos/{repo_id}/pipelines", body)
