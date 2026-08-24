# Verify commands by stack

Detect stack, run project scripts first (they encode project-specific rules), fall back to these.

```bash
ls package.json Cargo.toml go.mod pyproject.toml pom.xml 2>/dev/null
```

| Stack | Build/typecheck | Test |
|---|---|---|
| Python | `mypy .` / `ruff check .` | `pytest --tb=short` |
| JS/TS | `npx tsc --noEmit` | `npm test` |
| Go | `go build ./...` / `go vet ./...` | `go test -race ./...` |
| Rust | `cargo check` | `cargo test` |
| Java/Kotlin | `mvn compile` or `./gradlew build` | `mvn test` / `./gradlew test` |
| Generic | `make build` | `make test` |

For a phase touching only types/interfaces, build/typecheck is usually enough — save the full
test run for the phase where callers/tests actually change.
