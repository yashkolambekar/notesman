# Deploying on Coolify

1. **New resource → Docker Compose**, point it at this repo, compose file `docker-compose.yml`.
2. **Domain:** set it on the `web` service, port `3000`. Leave `api` and `worker` without a domain (internal only).
3. **Environment variables:** run `./scripts/compose-env.sh` for the list. Required ones fail the deploy if empty.
   - `PUBLIC_BASE_URL` = the exact https URL of the web domain (no trailing slash). It drives the login cookie and the Google redirect.
   - `SESSION_SECRET`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   - `API_KEY_ENCRYPTION_KEY`: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Encrypts the API keys admins save. Keep it stable; if it changes, admins must re-enter their keys.
   - `SUPERADMIN_EMAIL`: your Google account email.
   - `DATABASE_URL`: `postgres://user:pass@host:port/db`
4. **Google Cloud Console → OAuth client**: add redirect URI `https://<your-domain>/api/v1/auth/google/callback`.
5. Deploy. The API applies database migrations on every start. Run only **one** `worker` replica.

Changing `PUBLIC_BASE_URL` requires a rebuild (the web image bakes it in).
