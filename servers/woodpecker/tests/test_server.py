import asyncio

from woodpecker_mcp.server import mcp

EXPECTED_TOOLS = {
    "woodpecker_orgs",
    "woodpecker_org_permissions",
    "woodpecker_org_secrets",
    "woodpecker_org_registries",
    "woodpecker_repos",
    "woodpecker_repo_branches",
    "woodpecker_repo_permissions",
    "woodpecker_repo_pull_requests",
    "woodpecker_repo_secrets",
    "woodpecker_repo_registries",
    "woodpecker_repo_cron",
    "woodpecker_pipelines",
    "woodpecker_pipeline_config",
    "woodpecker_pipeline_metadata",
    "woodpecker_pipeline_logs",
    "woodpecker_queue_pipelines",
    "woodpecker_queue_info",
    "woodpecker_secrets",
    "woodpecker_registries",
    "woodpecker_agents",
    "woodpecker_agent_tasks",
    "woodpecker_forges",
    "woodpecker_users",
    "woodpecker_user_self",
    "woodpecker_user_feed",
    "woodpecker_user_repos",
    "woodpecker_server_info",
    "woodpecker_create_org_secret",
    "woodpecker_trigger_pipeline",
}


def test_tools_registered():
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOLS, names


if __name__ == "__main__":
    test_tools_registered()
    print("ok")
