# Checks

Compiler, linter and tests give the same diagnostics an LSP would, without a server. Use them as evidence.

## Order of preference

1. The project's own entry point: `Makefile`/`justfile` target (`check`, `lint`, `test`), CI config (`.github/workflows`, `.woodpecker`, `.gitlab-ci.yml`), `.pre-commit-config.yaml`, `package.json` scripts, `tox.ini`/`noxfile.py`. Run what the project runs.
2. Otherwise the table below, only for tools that exist (`command -v <tool>`).

## Rules

- Diagnostics only. Never install, update, migrate, format-in-place, `git commit/checkout/stash`, or touch the network except documentation lookups.
- Use the check variants that do not rewrite sources (`--check`, `--noEmit`, `-n`, `--dry-run`).
- Build artifacts (`target/`, `__pycache__`, `.mypy_cache`) are fine. Source files are not.
- Prefer the narrowest scope that covers the diff (a package, a file) before the whole workspace.
- Use a timeout (`timeout 120 <cmd>`). A slow check: report it and skip, do not wait forever.
- Tool missing: say which one and what it would catch. Do not install it.
- These commands run project code (build scripts, test code, linter plugins). That is the user's own code; still, if a repo is untrusted, ask first.
- Quote the first relevant lines of output exactly. Do not paste walls of text.

## By language

| Language | Compile / types | Lint / format check | Tests |
|---|---|---|---|
| Rust | `cargo check --all-targets` | `cargo clippy --all-targets`, `cargo fmt --check` | `cargo test` |
| Go | `go build ./...` | `go vet ./...`, `gofmt -l .`, `staticcheck ./...` | `go test ./...` (`-race` for concurrency) |
| Python | `mypy .` or `pyright` if configured | `ruff check .`, `ruff format --check .` | `pytest -q` |
| TypeScript | `tsc --noEmit` | `eslint .`, `prettier --check .` | the `test` script |
| JavaScript | n/a | `eslint .` | the `test` script |
| C / C++ | the build system's configure+build (`cmake --build`, `make -n` to preview) | `clang-tidy -p build <files>`, `cppcheck --enable=warning,performance <files>` | `ctest` |
| Zig | `zig build` | `zig fmt --check .` | `zig build test` |
| Java | `mvn -q -o compile` / `gradle compileJava --offline` | `checkstyle`/`spotbugs` if configured | `mvn -q -o test` / `gradle test --offline` |
| C# | `dotnet build --no-restore` | `dotnet format --verify-no-changes` | `dotnet test --no-build` |
| Ruby | n/a | `rubocop` | `rspec` / `rake test` |
| Shell | `bash -n file` | `shellcheck file` | n/a |

Commands above are starting points to be confirmed against the project's config. Flags and tools
change between versions: when in doubt, read the tool's `--help` or its official docs before relying on it.

## Reading the output

- A lint id (`clippy::needless_borrow`, `E501`, `SC2086`) has an official explanation page. Open it and cite it rather than explaining from memory.
- Group repeated diagnostics into one item instead of listing them N times.
- A failing test is the best teaching moment: ask the user to predict why it fails before explaining.
