from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP

from . import tools as t
from .client import WoodpeckerClient, open_woodpecker
from .config import load_config


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[WoodpeckerClient]:
    config = load_config()
    client = open_woodpecker(config)
    try:
        yield client
    finally:
        client.close()


mcp = FastMCP("woodpecker", lifespan=lifespan)


def _client(ctx: Context) -> WoodpeckerClient:
    return ctx.request_context.lifespan_context


@mcp.tool()
def woodpecker_orgs(ctx: Context, org_id: int | None = None, full_name: str | None = None) -> object:
    """List all organizations, get one by id, or look one up by full name."""
    return t.woodpecker_orgs(_client(ctx), org_id, full_name)


@mcp.tool()
def woodpecker_org_permissions(ctx: Context, org_id: int) -> object:
    """Get the current user's permissions for an organization."""
    return t.woodpecker_org_permissions(_client(ctx), org_id)


@mcp.tool()
def woodpecker_org_secrets(ctx: Context, org_id: int, name: str | None = None) -> object:
    """List an organization's secrets, or get one by name."""
    return t.woodpecker_org_secrets(_client(ctx), org_id, name)


@mcp.tool()
def woodpecker_org_registries(ctx: Context, org_id: int, name: str | None = None) -> object:
    """List an organization's container registries, or get one by address/name."""
    return t.woodpecker_org_registries(_client(ctx), org_id, name)


@mcp.tool()
def woodpecker_repos(ctx: Context, repo_id: int | None = None, full_name: str | None = None) -> object:
    """List all repositories on the server, get one by id, or look one up by full name (owner/name)."""
    return t.woodpecker_repos(_client(ctx), repo_id, full_name)


@mcp.tool()
def woodpecker_repo_branches(ctx: Context, repo_id: int) -> object:
    """List branches of a repository."""
    return t.woodpecker_repo_branches(_client(ctx), repo_id)


@mcp.tool()
def woodpecker_repo_permissions(ctx: Context, repo_id: int) -> object:
    """Get the current user's permissions for a repository."""
    return t.woodpecker_repo_permissions(_client(ctx), repo_id)


@mcp.tool()
def woodpecker_repo_pull_requests(ctx: Context, repo_id: int) -> object:
    """List active pull requests of a repository."""
    return t.woodpecker_repo_pull_requests(_client(ctx), repo_id)


@mcp.tool()
def woodpecker_repo_secrets(ctx: Context, repo_id: int, name: str | None = None) -> object:
    """List a repository's secrets, or get one by name."""
    return t.woodpecker_repo_secrets(_client(ctx), repo_id, name)


@mcp.tool()
def woodpecker_repo_registries(ctx: Context, repo_id: int, name: str | None = None) -> object:
    """List a repository's container registries, or get one by name."""
    return t.woodpecker_repo_registries(_client(ctx), repo_id, name)


@mcp.tool()
def woodpecker_repo_cron(ctx: Context, repo_id: int, cron_name: str | None = None) -> object:
    """List a repository's cron jobs, or get one by name."""
    return t.woodpecker_repo_cron(_client(ctx), repo_id, cron_name)


@mcp.tool()
def woodpecker_pipelines(ctx: Context, repo_id: int, pipeline_number: int | None = None) -> object:
    """List a repository's pipelines, or get one by pipeline number."""
    return t.woodpecker_pipelines(_client(ctx), repo_id, pipeline_number)


@mcp.tool()
def woodpecker_pipeline_config(ctx: Context, repo_id: int, pipeline_number: int) -> object:
    """Get the resolved config files used by a pipeline run."""
    return t.woodpecker_pipeline_config(_client(ctx), repo_id, pipeline_number)


@mcp.tool()
def woodpecker_pipeline_metadata(ctx: Context, repo_id: int, pipeline_number: int) -> object:
    """Get metadata for a pipeline run, including previous pipeline info."""
    return t.woodpecker_pipeline_metadata(_client(ctx), repo_id, pipeline_number)


@mcp.tool()
def woodpecker_pipeline_logs(ctx: Context, repo_id: int, pipeline_number: int, step_id: int) -> object:
    """Get logs for a single step of a pipeline run."""
    return t.woodpecker_pipeline_logs(_client(ctx), repo_id, pipeline_number, step_id)


@mcp.tool()
def woodpecker_queue_pipelines(ctx: Context) -> object:
    """List pipelines currently in the run queue, across all repos."""
    return t.woodpecker_queue_pipelines(_client(ctx))


@mcp.tool()
def woodpecker_queue_info(ctx: Context) -> object:
    """Get pipeline queue statistics (pending, running, worker capacity)."""
    return t.woodpecker_queue_info(_client(ctx))


@mcp.tool()
def woodpecker_secrets(ctx: Context, name: str | None = None) -> object:
    """List global (server-wide) secrets, or get one by name."""
    return t.woodpecker_secrets(_client(ctx), name)


@mcp.tool()
def woodpecker_registries(ctx: Context, name: str | None = None) -> object:
    """List global (server-wide) container registries, or get one by name."""
    return t.woodpecker_registries(_client(ctx), name)


@mcp.tool()
def woodpecker_agents(ctx: Context, agent_id: int | None = None, org_id: int | None = None) -> object:
    """List all agents, get one by id, or list agents scoped to an organization."""
    return t.woodpecker_agents(_client(ctx), agent_id, org_id)


@mcp.tool()
def woodpecker_agent_tasks(ctx: Context, agent_id: int) -> object:
    """List tasks currently assigned to an agent."""
    return t.woodpecker_agent_tasks(_client(ctx), agent_id)


@mcp.tool()
def woodpecker_forges(ctx: Context, forge_id: int | None = None) -> object:
    """List configured forges (Git hosting integrations), or get one by id."""
    return t.woodpecker_forges(_client(ctx), forge_id)


@mcp.tool()
def woodpecker_users(ctx: Context, login: str | None = None) -> object:
    """List all Woodpecker users, or get one by login."""
    return t.woodpecker_users(_client(ctx), login)


@mcp.tool()
def woodpecker_user_self(ctx: Context) -> object:
    """Get the currently authenticated user."""
    return t.woodpecker_user_self(_client(ctx))


@mcp.tool()
def woodpecker_user_feed(ctx: Context) -> object:
    """Get the currently authenticated user's pipeline activity feed."""
    return t.woodpecker_user_feed(_client(ctx))


@mcp.tool()
def woodpecker_user_repos(ctx: Context) -> object:
    """List repositories the currently authenticated user has access to."""
    return t.woodpecker_user_repos(_client(ctx))


@mcp.tool()
def woodpecker_server_info(ctx: Context) -> dict:
    """Get server version, health status, and signature public key."""
    return t.woodpecker_server_info(_client(ctx))


@mcp.tool()
def woodpecker_create_org_secret(
    ctx: Context,
    org_id: int,
    name: str,
    value: str,
    events: list[str] | None = None,
    images: list[str] | None = None,
    note: str | None = None,
) -> object:
    """Create an organization secret. events restricts which pipeline events can use it (e.g. push, tag, pull_request); images restricts which pipeline step images can use it."""
    return t.woodpecker_create_org_secret(_client(ctx), org_id, name, value, events, images, note)


@mcp.tool()
def woodpecker_trigger_pipeline(
    ctx: Context,
    repo_id: int,
    branch: str | None = None,
    variables: dict[str, str] | None = None,
) -> object:
    """Manually trigger a new pipeline run for a repository, optionally on a specific branch with extra variables."""
    return t.woodpecker_trigger_pipeline(_client(ctx), repo_id, branch, variables)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
