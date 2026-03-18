# Skill: Security

Read this file when working with `.env` files, credentials, deployment, or data cleanup.

## Secrets Management

- API keys and credentials live in `.env` (gitignored). Load via `python-dotenv`.
- `.env` file permissions must be `chmod 600`.
- `.env.example` in the repo contains placeholder values only, never real keys.
- Never log API keys, passwords, or credentials. Mask sensitive values in error messages. See also: `SKILLS/error-handling.md`.

## Browser Security

- The browser runs as an unprivileged user, never root.

## Data Cleanup

- Screenshots in `data/screenshots/` and AI responses in `data/ai_responses/` are gitignored.
- Auto-clean these directories after 30 days.

## Git Pre-Commit

- Verify no secrets in staged files.

## Database Credentials (V2+)

- MySQL credentials use a dedicated read-only user.
- Read-write access only added in V3.

## Email Credentials (V5)

- Gmail App Password (not main password) stored in `.env`.
- Sent via TLS on port 587.
