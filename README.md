# CHO-CBC-management

A starting point for related Python scripts, managed with [uv](https://docs.astral.sh/uv/).
Python 3.12 or newer is required.

## Route descriptions

Generate a Word document from a JSON file in `src/cho_cbc_management/data`:

```sh
uv run generate-route-description-document --routes 2026_routes.json
```

The document is written to `reports/2026_routes.docx` in the current directory.
Shared routes are marked PRIMARY in their first sector and listed at the end of
each other sector.

## Confirmation drafts

Set `MAIL_USERNAME` and `MAIL_PASSWORD` in a `.env` file in the current
directory. The username must match the compiler's email in the JSON. Gmail
typically requires a [Google app password](https://support.google.com/accounts/answer/185833),
which requires 2-Step Verification; regular account passwords are not supported.
Keep the `.env` file private. Then run:

```sh
uv run generate-confirmation-emails --email "Sector Confirmation" --routes 2026_routes.json
```

Use `--email "Route Confirmation"` for route leaders. Each sector or route gets
a draft addressed to all its captains or leaders, containing relevant route
details. Route drafts copy the sector captains. `--email "Captain Announcement"`
creates one draft to all captains; `--email "Participant Announcement"` creates
one draft with all captains, route leaders, route participants, and additional
participants in Bcc. Templates can specify `cc` and `bcc` as an email address,
recipient group, or list of these. Supported groups are `sector captains`,
`route leaders`, `route participants`, `additional participants`, and
`everyone`. Addresses are deduplicated across To, Cc, and Bcc. No emails are
sent. The script
replaces `{date}` in the message with the JSON `count date`, formatted with its
weekday. The date must be the last Saturday before Christmas Eve of the current
year; common formats such as `2026-12-19` and `December 19, 2026` are accepted.
It also replaces `{rain date}` with the JSON `rain date`, which must be the day
after the count date.
The script authenticates with `smtp.gmail.com:465` and saves drafts
via `imap.gmail.com:993`; the account must allow both connections. Use
`--compiler EMAIL` when there is more than one compiler, and `--env-file PATH`
to use an environment file in another location. Running the command again
creates additional drafts; it does not replace existing ones.

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