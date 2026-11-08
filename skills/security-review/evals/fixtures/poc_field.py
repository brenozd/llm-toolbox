#!/usr/bin/env python3
"""Shared PoC checker for the containers and kubernetes eval fixtures.

Prints a marker only when the named field is present and bad, and always exits 0, so
the negative control (the same check against the fixed twin) prints nothing. The Dockerfile
check is stdlib-only; the compose and k8s checks need PyYAML.

Usage: poc_field.py --kind {dockerfile,compose,k8s} --field FIELD --file PATH
See fixtures/README.md for the field list and the truth table.
"""

import argparse
import re
import sys
from pathlib import Path

# A variable name whose last word is a credential: `NPM_TOKEN` is one, `TOKEN_URL` is not.
SECRET_NAME = re.compile(r"(?:^|_)(?:TOKEN|SECRET|PASSWORD|PASSWD|APIKEY|API_KEY|CREDENTIALS?)$",
                         re.I)


def _docs(path):
    import yaml  # imported here so the Dockerfile check stays stdlib-only
    return [doc for doc in yaml.safe_load_all(Path(path).read_text()) if doc]


def _walk(node):
    """Every dict in a parsed document, at any depth."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _literal(value) -> bool:
    return isinstance(value, str) and value.strip() != "" and "$" not in value


# --------------------------------------------------------------------- dockerfile

def dockerfile_root_user(path) -> bool:
    """The last stage declares no USER, so the container runs as root."""
    stages = [[]]
    for line in Path(path).read_text().splitlines():
        if line.strip().upper().startswith("FROM "):
            stages.append([])
        stages[-1].append(line.strip())
    return not any(line.upper().startswith("USER ") for line in stages[-1])


def dockerfile_secret_env(path) -> bool:
    """An ENV exports a credential, so the value is baked into the image config."""
    for line in Path(path).read_text().splitlines():
        head = line.strip()
        if head.upper().startswith("ENV ") and SECRET_NAME.search(head.split()[1].split("=")[0]):
            return True
    return False


# ------------------------------------------------------------------------ compose

def _compose_services(path) -> dict:
    services = {}
    for doc in _docs(path):
        services.update((doc or {}).get("services") or {})
    return services


def compose_docker_sock(path) -> bool:
    for service in _compose_services(path).values():
        for volume in (service or {}).get("volumes") or []:
            source = volume.split(":")[0] if isinstance(volume, str) else \
                str((volume or {}).get("source", ""))
            if source == "/var/run/docker.sock":
                return True
    return False


def compose_env_secret(path) -> bool:
    for service in _compose_services(path).values():
        environment = (service or {}).get("environment") or {}
        pairs = (environment.items() if isinstance(environment, dict)
                 else (item.split("=", 1) for item in environment if isinstance(item, str) and "=" in item))
        for name, value in pairs:
            if SECRET_NAME.search(str(name)) and _literal(value):
                return True
    return False


# ---------------------------------------------------------------------------- k8s

def k8s_privileged(path) -> bool:
    for doc in _docs(path):
        for node in _walk(doc):
            context = node.get("securityContext")
            if isinstance(context, dict) and context.get("privileged") is True:
                return True
    return False


def k8s_cluster_admin(path) -> bool:
    for doc in _docs(path):
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") in ("ClusterRoleBinding", "RoleBinding") and \
                (doc.get("roleRef") or {}).get("name") == "cluster-admin":
            return True
    return False


def k8s_plaintext_secret(path) -> bool:
    for doc in _docs(path):
        for node in _walk(doc):
            for key, value in node.items():
                if SECRET_NAME.search(str(key)) and _literal(value):
                    return True
    return False


CHECKS = {
    ("dockerfile", "root-user"): ("CONTAINERS_ROOT_USER_CONFIRMED", dockerfile_root_user),
    ("dockerfile", "secret-env"): ("CONTAINERS_SECRET_ENV_CONFIRMED", dockerfile_secret_env),
    ("compose", "docker-sock"): ("CONTAINERS_DOCKER_SOCK_CONFIRMED", compose_docker_sock),
    ("compose", "env-secret"): ("CONTAINERS_ENV_SECRET_CONFIRMED", compose_env_secret),
    ("k8s", "privileged"): ("KUBERNETES_PRIVILEGED_CONFIRMED", k8s_privileged),
    ("k8s", "cluster-admin"): ("KUBERNETES_CLUSTER_ADMIN_CONFIRMED", k8s_cluster_admin),
    ("k8s", "plaintext-secret"): ("KUBERNETES_PLAINTEXT_SECRET_CONFIRMED",
                                  k8s_plaintext_secret),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="confirm one bad field in an artifact")
    parser.add_argument("--kind", required=True, choices=sorted({k for k, _ in CHECKS}))
    parser.add_argument("--field", required=True,
                        choices=sorted({f for _, f in CHECKS}))
    parser.add_argument("--file", required=True)
    args = parser.parse_args(argv)
    marker, check = CHECKS.get((args.kind, args.field), (None, None))
    if marker is None:
        print(f"unknown check: {args.kind}/{args.field}")
        return 0
    if not Path(args.file).is_file():
        print(f"cannot read {args.file}")
        return 0
    if check(args.file):
        print(marker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
