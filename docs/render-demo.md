# ALU Helios demo on Render Free

This is a small testing demo, not a production election or a 10,000-voter
deployment. All changes are local until you authorize a commit, push, and deploy.
Creating a Render Blueprint starts a deployment even with auto-deploy disabled.

## Deployment, after authorization

1. Review these files, commit/push the approved changes to your existing GitHub
   fork, then choose **New → Blueprint** in Render and select that fork/branch.
2. Use `render.yaml`. Verify both `alu-helios-demo` and `alu-helios-demo-db` use
   **Free** and the same region. If your workspace already has a Free PostgreSQL
   database, reuse it and configure its internal connection string instead.
3. Supply the Google web OAuth client ID and secret privately in Render. Never
   put secrets in source control, screenshots, or chat. Render generates the two
   application secrets and injects the database URL. Keep these secrets stable.
4. The Docker image installs Python 3.13, locked Python dependencies, and LDAP
   build libraries. Startup runs Django checks and migrations, then one Gunicorn
   worker with a 180-second timeout. No worker or RabbitMQ service is required.
5. Record the **actual** public URL from Render. `RENDER_EXTERNAL_HOSTNAME`
   supplies exact allowed hosts and the HTTPS `URL_HOST`/`SECURE_URL_HOST`.
   If using a custom domain, set `ALLOWED_HOSTS` to comma-separated hostnames and
   `URL_HOST` to the canonical HTTPS origin. No trailing slash.
6. Confirm `/`, `/booth/vote.html`, `/verifier/verify.html`, and a referenced
   `/static/helios/` asset load over HTTPS. This fork serves booth, verifier, and
   assets through explicit Django routes, including with `DEBUG=False`;
   `collectstatic`/WhiteNoise are not required for this demo.

The existing eight-worker `Procfile` is bypassed by Docker's start command.
`settings_render_demo` requires `HELIOS_DEMO_MODE=1`, disables debug and all login
systems except Google, enables secure cookies/proxy handling, and uses eager
Celery with propagated errors and a memory broker. Notification code uses a dummy
email backend: no mail is sent or logged, and SMTP cannot break casting/tallying.
You must save ballot trackers in the browser; there is no receipt email.

The domain `alustudent.com` was found in the separate frontend's
`src/lib/auth/access.ts` (`ALU_STUDENT_DOMAIN` default) and `src/lib/types.ts`.
No local `.env` override was found. Helios checks the exact domain of Google's
verified email on its server; a client-side check or Google's `hd` hint is not
the authorization decision. Registration also rejects other authentication
systems, unverified/stale identities, and other domains while the setting is on.
Existing sessions predating this change should be logged out and reauthenticated.

## Google OAuth with the actual Render URL

In Google Cloud's Google Auth Platform, configure the consent screen/audience,
then create an OAuth client of type **Web application**. Use:

- Authorized JavaScript origin: `https://<actual-render-hostname>`
- Authorized redirect URI: `https://<actual-render-hostname>/auth/after/`

The trailing slash on the redirect is required. Use the same project/client as
the credentials in Render. For an external app in Testing, add your demo student
accounts as test users where required by Google's consent configuration. An
internal Workspace app requires authorization within that Workspace. Do not
assume you can administer ALU's Workspace. The client requests only OpenID,
email, and profile scopes. Save the configuration and retry a real student login.

## Complete mock election

1. Open the service a few minutes before presenting and sign in with a verified
   `@alustudent.com` Google account. The demo retains Helios's default permission
   for authenticated users to create elections; the creator administers their
   own election. Use a student organizer account for this demo.
2. Create a clearly named **TEST** election. Use a public election for easy
   auditing; encrypted choices remain private. Enable voter aliases if you want
   aliases on public voter lists (this is separate from ballot secrecy).
3. Add one question and two choices. Keep the automatically created Helios
   trustee for this small test. In the voter list, select **open registration**
   before freezing. Do not upload a roster. The eligibility summary should say
   that only verified Google accounts at `@alustudent.com` can register.
4. Freeze the election only after checking questions, trustees, and registration.
   Keep open registration enabled while voting so new student accounts can join.
5. In a separate browser session, sign in as a second student, open the election,
   encrypt a choice in the booth, and confirm the ballot. Helios creates the voter
   automatically on ballot confirmation, not immediately after a homepage login.
   Confirm there is one voter entry and one verified cast ballot.
6. Save the tracker. Open its ballot link and compare its fingerprint to the
   receipt. Use the linked verifier to verify the encrypted ballot/election.
   Optionally audit a separate trial ballot to check its plaintext/randomness;
   an audited ballot is spoiled and must not be cast. Encrypt a fresh ballot.
7. Try a nonstudent Google account in another session: it must fail login and
   create neither a Helios user nor voter entry. Do not add it to the election.
8. As the election creator, choose **compute encrypted tally** (this closes
   voting), wait for the request to finish, then combine decryptions and release
   results. With only the Helios trustee, its decryption/proofs run synchronously.
   Check the result matches the known test choices and verify the tally using
   Helios's verification tools. Confirm another vote cannot be cast after closing.

The default single Helios trustee makes this a demonstration of the workflow;
independent trustees and a production security/operations review come later.
Synchronous crypto blocks the only web worker during processing. Keep the demo
small and do not redeploy/restart while casting or tallying.

## Verification

With Python 3.13, `uv`, LDAP libraries, and local PostgreSQL running as configured
in `settings_ci.py`:

```sh
uv sync --frozen
uv run python manage.py test --settings=settings_ci -v 1
uv run python manage.py test helios.test_render_demo --settings=settings_ci -v 2
```

The added integration test mocks only Google's network exchange. It exercises
the auth callback, exact domain checks, automatic voter creation without a
roster, real encrypted ballot/proof verification and storage through eager
Celery, closing, nested eager trustee decryption, result combination and release.
The existing complete-election tests additionally cover ballot casting/tallying.
This does not replace a real browser OAuth/booth/verifier test on the deployed URL.

Local verification completed with Python 3.13.16 and an isolated PostgreSQL 16
database: **all 219 tests passed**, including the five demo tests and existing
complete-election tests. Django's ordinary system check, Python/shell syntax,
and whitespace checks passed. The demo `check --deploy` has two known warnings:
Helios uses its existing custom CSRF checks instead of Django's CSRF middleware,
and this temporary demo does not enable HSTS. The Docker image has not been built
locally (Docker is unavailable), and live OAuth/browser verification awaits the
authorized deployment and its actual URL.

Render Free sleeps after 15 minutes without inbound traffic and can take about
a minute to wake. Free PostgreSQL expires after 30 days; export anything needed
before expiry. Free services have ephemeral disks and cannot send SMTP traffic
on ports 25, 465, or 587. These limits are documented in
[Render's Free guide](https://render.com/docs/free). Configuration follows the
[Blueprint reference](https://render.com/docs/blueprint-spec) and
[Render environment variables](https://render.com/docs/environment-variables).
OAuth setup follows [Google's web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server).
