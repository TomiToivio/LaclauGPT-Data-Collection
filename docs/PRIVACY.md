# Public Repository Privacy and Configuration Policy

This repository is intended to be publishable at all times.

## Never commit

The following are forbidden in Git history, even on temporary branches:

- API keys, access tokens, refresh tokens, passwords, private keys, cookies or browser storage state.
- `.env` files or real deployment configuration.
- CSC Allas/OpenStack credentials, S3 access keys, SSH credentials, VPN configuration or private service endpoints.
- Real research target/account/channel lists unless they are deliberately approved for publication.
- Collected posts, comments, profiles, videos, images, audio, PDFs, raw API responses, exports, researcher workbooks or derived participant-level data.
- Browser profiles, HAR files from real sessions, session databases or authentication artifacts.
- Private-repository paths or copied files whose publication status has not been reviewed.

## Allowed configuration

Checked-in configuration must be one of:

1. a schema;
2. an example containing placeholders only; or
3. a synthetic test fixture.

Public examples must use values such as `localhost`, `example.invalid`, `bucket-name`, `replace-locally` and synthetic handles.

Secrets are read from environment variables or an ignored local secret store. Operational study configuration belongs in a private repository or deployment system.

## Data boundary

All runtime data must live outside the repository working tree when practical. If a local path is used, it must be covered by `.gitignore`.

The code may write JSONL, CSV, SQLite, MongoDB, Redis or S3, but **no collected output is a source file**.

## Pull-request checklist

Before merging any PR:

- inspect changed files for data/config additions;
- search for tokens, passwords, cookies, emails, phone numbers, IPs/hostnames and filesystem paths that look operational;
- verify fixtures are synthetic;
- verify new collectors accept targets and credentials through runtime configuration;
- verify logs do not print secrets;
- verify documentation contains placeholders only.

## If restricted material is committed

Do not merely delete the file in a later commit. Assume the material remains recoverable from history.

1. Revoke or rotate credentials immediately.
2. Remove the material from every branch/tag and rewrite history.
3. Force-push the sanitized history while the repository is still private.
4. Re-clone and scan the rewritten repository.
5. Only then change repository visibility.

For data that cannot be made public, keep the canonical artifact in private storage and publish only code, schemas and synthetic examples here.
