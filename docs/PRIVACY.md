# Public Repository Privacy and Configuration Policy

This repository is intended to be publishable at all times. Treat every commit, branch and pull request as potentially public immediately.

## Never commit

The following are forbidden in Git history, even on temporary branches:

- API keys, access tokens, refresh tokens, passwords, private keys, cookies or browser storage state.
- `.env`, `.envrc`, `.netrc`, Streamlit secrets or real deployment configuration.
- CSC Allas/OpenStack credentials, S3 access keys, SSH credentials, VPN configuration, Terraform state, Kubernetes config or private service endpoints.
- Credential-bearing connection strings such as `scheme://user:password@host`.
- Real research target/account/channel lists unless they are deliberately approved for publication.
- Collected posts, comments, profiles, videos, images, audio, PDFs, raw API responses, exports, researcher workbooks or derived participant-level data.
- Browser profiles, HAR/PCAP network captures from real sessions, session databases or authentication artifacts.
- Private-repository paths or copied files whose publication status has not been reviewed.
- Machine-specific paths that reveal private usernames, home directories, project allocations or restricted storage locations.

## Configuration boundary

Checked-in configuration must be one of:

1. a schema;
2. an example containing placeholders only; or
3. a synthetic test fixture.

Public examples must use values such as `localhost`, `example.invalid`, `bucket-name`, `replace-locally` and synthetic handles. Example files must be clearly named, for example `*.example.toml` or `.env.example`.

Real operational configuration belongs outside Git. Preferred locations are environment variables, ignored local files, a deployment secret manager, or a private operations repository. Do not create a real config file first and rely on remembering not to stage it later.

Secrets are read from environment variables or an ignored local secret store. Collector target lists that could reveal study design, participants or monitored accounts should be supplied at runtime or stored privately.

## Data boundary

All runtime data should live outside the repository working tree when practical. If a local path is used, it must be covered by `.gitignore`.

The code may write JSONL, CSV, SQLite, MongoDB, Redis or S3, but **no collected output is a source file**. The same rule applies to screenshots, downloaded media, browser captures, HAR/PCAP traces, manifests, caches and researcher exports.

Tests must use synthetic data only. A synthetic fixture must not be a lightly edited copy of a real post, profile, account list or private API response.

## Automated publication barrier

CI runs `python scripts/check_public_tree.py`. The scanner rejects common data formats, private/config filenames, infrastructure state, private-key material, literal secret assignments and credential-bearing URLs.

The scanner is a backstop, not authorization to commit questionable material. Human review remains required because no regex can determine whether a target list, prose document or synthetic-looking fixture is actually safe to publish.

Before pushing, run:

```bash
python scripts/check_public_tree.py
ruff check .
mypy src/laclaugpt_data_collection
pytest
```

`ruff format .` is recommended for touched Python files. Formatting of older imported modules is being normalized incrementally rather than used as a repository-wide publication gate.

## Pull-request checklist

Before merging any PR:

- inspect changed files for data/config additions;
- search for tokens, passwords, cookies, emails, phone numbers, IPs/hostnames and filesystem paths that look operational;
- check connection strings for embedded credentials;
- verify fixtures are synthetic;
- verify new collectors accept targets and credentials through runtime configuration;
- verify logs and `doctor`/debug output do not print secrets;
- verify documentation contains placeholders only;
- confirm the public-tree scanner and tests pass.

## If restricted material is committed

Do not merely delete the file in a later commit. Assume the material remains recoverable from history.

1. Revoke or rotate credentials immediately.
2. Remove the material from every branch/tag and rewrite history.
3. Inspect pull-request refs and cached commit views as well as normal branches.
4. Force-push the sanitized history while the repository is still private when possible.
5. Re-clone and scan the rewritten repository.
6. If GitHub still retains sensitive pull-request refs, contact GitHub Support for dereferencing/garbage collection or publish from a fresh clean repository.
7. Only then expose the repository publicly.

For data that cannot be made public, keep the canonical artifact in private storage and publish only code, schemas and synthetic examples here.
