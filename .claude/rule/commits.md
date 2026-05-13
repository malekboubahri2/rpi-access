# Commit guidelines

Generic rules for writing commits in this and any repo I work on with you.

## Format — Conventional Commits

```
<type>(<scope>): <subject>

<body — optional, wrap at 72 cols>

<footer — optional: breaking changes, refs>
```

| `<type>` | Use for                                                       |
|----------|---------------------------------------------------------------|
| `feat`   | A new user-visible feature                                    |
| `fix`    | A bug fix                                                     |
| `docs`   | Documentation only                                            |
| `test`   | Tests added or fixed (no production code change)              |
| `refactor` | Internal restructuring with no behaviour change             |
| `perf`   | Performance improvement with no API/behaviour change          |
| `chore`  | Build, deps, CI, repo hygiene, generated files                |
| `style`  | Whitespace, formatting, lints — no semantic change            |
| `revert` | Reverts a previous commit (reference its hash in the body)    |

Scope is the top-level module / area touched (`core`, `wifi`, `portal`,
`ui`, `security`, `boot`, `ci`, `deps`, …). Omit it when the change is
genuinely repo-wide.

## Subject line

* Imperative mood (`add`, not `added`, not `adds`).
* Lowercase except proper nouns.
* No trailing period.
* Under 72 characters; aim for 50.
* Say *what* changed, not *why* — the body is for *why*.

Good:
- `feat(wifi): add scanner with nmcli output parsing`
- `fix(portal): drop duplicate "/" rule between blueprints`
- `chore(deps): pin cryptography to 42.0.8`

Bad:
- `Updated some files.`
- `fixed bug`
- `feat: i added a new endpoint that lets you connect to wifi networks by SSID and password and it also handles captive portals`

## Body

Optional but encouraged when the change is non-trivial. Cover:

1. **Why** the change exists (the problem, not the solution).
2. **What changed at a high level**, if the diff isn't obvious.
3. **Trade-offs / alternatives considered**, when relevant.
4. **Risk** — what to watch in production, what might regress.

Leave a blank line between subject and body.

## Atomic, ordered commits

* Each commit should compile, lint, and pass tests on its own.
* One logical change per commit. Don't bundle a feature with an
  unrelated refactor.
* Prefer many small commits over one giant one — easier to review,
  bisect, and revert.
* Order commits so an outside reader can follow the work: scaffolding
  first, modules in dependency order, tests right after the code they
  cover, docs last.

## What NOT to commit

* Secrets (`.env`, credentials, private keys, API tokens).
* Generated artifacts already covered by `.gitignore`
  (`__pycache__/`, `dist/`, `node_modules/`, `.venv/`).
* Personal IDE config (`.vscode/settings.json`, `.idea/`).
* WIP commits on shared branches — squash them before pushing.

## Footer

Use trailers when applicable:

* `BREAKING CHANGE: <description>` — bumps the major version.
* `Refs #123` / `Closes #123` / `Fixes #123` — issue cross-refs.
* `Co-Authored-By: Name <email>` — pair / triple work.

## Co-authorship

When AI assistance contributed materially to a commit, add it as a
co-author so the diff history is honest:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

## Examples of progressive commit ordering

For a new module / repo, walk in dependency order:

```
chore: initialise repository structure
feat(core): add config loader, logger, state machine, exceptions
feat(<module-a>): add lowest-level component
feat(<module-b>): add component that depends on a
feat(<module-c>): add top-level integration
feat(<ui>): add user-facing surface
chore: add systemd unit, healthcheck, helper scripts
chore: add idempotent installer / uninstaller
test: add unit tests for the new modules
docs: add architecture, API, and troubleshooting docs
```

## Commands

```bash
# Use a heredoc to preserve formatting:
git commit -m "$(cat <<'EOF'
feat(wifi): add scanner with nmcli output parsing

Parses the terse `nmcli -t -f SSID,SIGNAL,SECURITY,FREQ,IN-USE,BSSID`
output into typed records, deduplicating by SSID and keeping the
strongest BSSID. Hidden networks (empty SSID) are dropped.
EOF
)"

# Stage selectively — never `git add .` blindly.
git add src/<module> tests/<module>

# Inspect before committing.
git status
git diff --staged
```

## Rules of thumb

* **If you can't explain why this commit exists in one sentence, split it.**
* **If the subject line needs "and", split it.**
* **Never `git push --force` to a shared branch without explicit approval.**
* **Never skip pre-commit hooks (`--no-verify`) to make a commit go through.**
* **Treat `main` / `master` as protected — go through a PR.**
