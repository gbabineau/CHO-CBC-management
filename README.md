# CHO-CBC-management

A starting point for related Python scripts, managed with [uv](https://docs.astral.sh/uv/).
Python 3.12 or newer is required.

## Development

Install uv, then from the repository root run:

```sh
uv sync --locked
uv run cho-cbc-management
uv run pytest --cov=cho_cbc_management --cov-report=xml
uv build
```

Add shared code and scripts under `src/cho_cbc_management`, register new commands
in `[project.scripts]` in `pyproject.toml`, and put unit tests in `tests/`.
Use `uv add` or `uv add --dev` to add dependencies and commit both
`pyproject.toml` and `uv.lock`.

## CI and SonarQube

GitHub Actions runs tests, generates coverage, builds the package, and scans it
with SonarQube on pushes and pull requests. To enable scanning, create a
SonarQube project with the key in `sonar-project.properties` (or update that
key), and set the repository secrets `SONAR_HOST_URL` (the server URL) and
`SONAR_TOKEN` (a token with permission to analyze the project). The server must
be reachable from GitHub-hosted runners. Pull request analysis requires a
SonarQube edition that supports it.

For pull requests from forks, tests and builds still run, but the scan is
skipped because repository secrets are unavailable. Dependabot checks Python
dependencies and GitHub Actions weekly.