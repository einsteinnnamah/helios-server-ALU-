# ALU Helios shared-login demo on free hosting

For the integrated creation, voting and receipt screens, see
[ALU UI integration](alu-ui-integration.md). Apply its additional Neon migration
before deploying the updated frontend.

This is a small TEST election, not production or a 10,000-voter deployment.
Use Render Free web + Free PostgreSQL and the existing Vercel Hobby frontend.
Do not configure Google OAuth in Helios. Neon Auth remains the login provider.

## Login and security

The frontend `/helios` page links to each explicitly enabled election. Helios
creates a signed, five-minute browser request bound to that election, its client,
its exact callback, and a secret PKCE verifier in the Helios browser session.
The frontend uses `auth.getSession` with cookie-cache bypass and requires a
verified `alustudent.com` email and a live matching Neon user/session. Already
signed-in students continue without another Google authentication. Signed-out
students use the existing Neon Google sign-in, then resume the handoff.

A random 256-bit code lives at most 60 seconds. Neon stores only its SHA-256 hash,
browser-request hash, bindings, and validated session identity. The authenticated
HTTPS exchange atomically deletes the matching row and rechecks the managed
user's current email verification and live session. Wrong state, verifier,
client, election, expired or replayed codes fail. Helios also locks and consumes
its browser request before exchange, rotates its session and CSRF token, checks
student eligibility independently, and scopes voting access to the election.
Codes travel in URL fragments and POST bodies, not query strings. Responses use
no-store/no-referrer; application handlers do not log codes, cookies or secrets.
Do not enable request-body/header logging in hosting or observability tools.

Voting access grants no committee/admin role. Existing Neon committee capability
checks remain unchanged. Helios preserves existing `admin_p` and election-admin
relationships for the same stable Neon user ID; it never links by email or grants
roles at login. Existing committee roles in Next.js do not automatically imply
Helios administration. An operator must explicitly authorize the appropriate
Helios election administrator. Students without that grant cannot close or tally.

Committee members (any active assignment to a role marked `is_official`) cannot
vote, including trustees and student administrators. The server determines this
from Neon role tables at code issuance. Committee codes are **access-only**;
Helios accepts them only for an existing authorized election administrator, with
no voter enrollment. A voter code issued before appointment fails redemption
while the committee role is active. Helios checks current membership over an
authenticated HTTPS backchannel on registration/confirmation and immediately
before saving a cast ballot. Existing voter registrations and sessions are no
exception. Missing/failed eligibility checks deny voting without clearing
committee login or administrator permissions. Existing sessions predating these
changes must restart the handoff.

Membership triggers preserve appointment history even after revocation or role
reclassification. At a blocked returning vote, the administrator's **ballot policy
reviews** page, and before tally/decryption combination/result release, Helios
checks stored voters against this history. Joining after casting creates a durable
pending review and blocks tallying; ciphertext, trackers and proofs stay intact.
An existing authorized Helios administrator may explicitly choose **retain** with
a policy reason, recorded actor and time. There is no automatic retention or
exclusion. If policy requires exclusion, stop and arrange a separately reviewed
exclusion process. New appointments create new reviews, including after a prior
retain decision. Reviews are discovered on these checks, not by a background
worker; after public result release they flag a governance issue without rewriting
the published result.

## Configure and deploy

1. Commit/push the reviewed changes in both repositories. In Render use
   **New → Blueprint**, select the Helios fork/master and `render.yaml`.
   Confirm `alu-helios-demo` and `alu-helios-demo-db` both show **Free** in
   Frankfurt. Do not enable a disk, worker, broker or paid database.
2. Set Render `ALU_BRIDGE_APP_ORIGIN=https://alu-election-app.vercel.app`.
   Privately generate a random shared secret of at least 32 bytes and set the
   SAME `ALU_BRIDGE_SECRET` in Render and the frontend's Vercel Production
   environment. Keep it server-only; never use `NEXT_PUBLIC_` or commit it.
   Render generates stable `SECRET_KEY` and `EMAIL_OPTOUT_SECRET` and supplies
   the database URL. Do not reveal credentials in screenshots/chat.
3. Record the actual Render public HTTPS URL. In Vercel Production set
   `HELIOS_BASE_URL` to that origin, and ensure `APP_BASE_URL` is exactly
   `https://alu-election-app.vercel.app`. Both services use
   `ALU_BRIDGE_CLIENT_ID=alu-helios-demo`. Set `ALU_BRIDGE_ELECTIONS` on BOTH
   services to the same comma-separated demo election UUIDs (no whitespace).
   Empty allowlists deliberately disable bridge election access.
4. Apply ONLY the new Neon bridge migration from the frontend root:
   `node --env-file=.env scripts/migrate-helios-bridge.mjs`.
   Use the existing correct Neon DATABASE_URL privately. This applies only migrations 0012 and 0013, creating authentication grants
   and private committee-transition history; do not run unrelated pending migrations for this demo.
5. Bootstrap a clearly named TEST election and explicitly authorized organizer
   using `python manage.py setup_alu_demo --election-id <uuid>
   --admin-subject <actual-Neon-user-id> --admin-email <verified-student-email>`.
   Use Render's database through a private local environment if Free does not
   offer a shell. Obtain the stable UUID from the managed Neon user record, not
   the browser or an email-derived guess. Select an organizer already authorized
   for election administration. This command is an explicit operator grant for
   THIS election; ordinary bridge login never performs it. The election starts
   as a draft with open registration, two choices, and a Helios trustee. Freeze
   it in the authorized organizer UI after checking the configuration.
6. Redeploy Vercel after environment changes, and deploy the latest Helios commit.
   No changes to the existing Neon Google OAuth configuration are needed unless
   the frontend origin itself changes. Never register Render as a Google callback.
7. Check `/`, `/booth/vote.html`, `/verifier/verify.html`, and referenced static
   assets over HTTPS. This fork serves these through Django routes; it does not
   need WhiteNoise/collectstatic. Docker starts one Gunicorn worker, runs checks
   and migrations, and uses eager Celery + memory transport. No SMTP is sent/logged.

## Mock election verification

1. Sign in on the frontend as the authorized organizer, then open `/helios`.
   Handoff should use the current Neon session without another Google prompt.
   Verify questions, registration, trustee, and freeze the TEST election.
2. In a separate browser session, sign in as a second verified student **with no active committee post** and enter
   the same election. Encrypt a ballot in Helios's booth and confirm it. Helios
   automatically creates the voter on ballot confirmation; there is no roster.
   Repeated confirmation must not create duplicate voter records.
3. Save the tracker, compare it with the published ballot fingerprint, and use
   the linked verifier. An audited ballot is spoiled: encrypt a fresh ballot to
   cast. Encryption, proofs, ballot verification and tallying are unchanged.
4. Check a nonstudent/unverified account fails; a student cannot access tally/admin
   endpoints; an explicitly authorized organizer retains their existing access.
5. Verify a committee member retains authorized back-office access but cannot
   vote using direct `/cast`, `/cast_confirm` or `/register` URLs, an existing
   voter session, or a voter code issued before appointment. In a separate TEST
   election, appoint a student after casting: check **ballot policy reviews**,
   confirm the ballot remains verified, and record an explicit policy decision
   before tallying. Do not delete their ballot.
6. Organizer: compute encrypted tally (closes voting), combine decryptions, release
   results and verify they match the known test votes. Confirm voting is closed.
   Eager mode runs ballot processing and nested trustee decryption synchronously.

## Checks and remaining operational limits

Local Helios verification: 234 tests pass, including real encryption, registration,
proof verification, eager casting/tallying and bridge browser security tests.
Frontend security tests use production handlers and an isolated PostgreSQL database:
replay, expiry, concurrent redemption, tampered signature, client/election/callback
binding, ineligible identities, unauthenticated exchange, revocation and email change, committee-only grants, prior-code rejection, role
reclassification and preserved appointment history (37 checks).
Use Node 24 for the frontend test scripts. Run `node scripts/test-helios-bridge.mjs` with `BRIDGE_TEST_DATABASE_URL` pointing
ONLY to the isolated local `bridge_test` fixture database; it creates mock managed
Auth tables there, never in Neon. Run Helios tests with `settings_ci` and PostgreSQL.
The Docker image builds successfully on the free public CI runner, and its encrypted-election tests and strict demo runtime check pass. Render Free startup and the hosted HTTPS exchange are verified. The existing Neon browser session opened Helios without another Google login; organizer controls were preserved and direct ballot confirmation returned 403 for the committee account. Live casting and tallying still require a verified noncommittee student account.

Helios bridge sessions last at most five minutes; Neon revocation after exchange
can take that long to invalidate an existing Helios session. The shared secret
and both app servers are trusted identity boundaries. Membership is checked
fresh on casting, but Neon membership changes and Helios ballot writes use
separate databases: they do not form a distributed transaction. A concurrent
appointment can race the final check; the subsequent policy check flags a current
committee member's stored ballot. Historical comparisons use provider UTC clocks.
Do not treat this as production-grade serialization of role changes and casting;
production requires a role freeze or coordinated authorization/commit protocol.
The fresh eligibility service must be available for casting and policy checks. This is a custom bridge,
not an externally audited identity protocol. Rotate the secret on compromise;
review managed Auth schema compatibility before upgrades. Expired codes are removed on subsequent authorization requests. The single Helios trustee is a demo setup.
Synchronous crypto blocks the sole web worker: keep the election small and do not
restart during casting/tallying. Existing custom CSRF checks are retained; this
short demo does not enable HSTS. Save ballot trackers locally: there is no mail.

[Render Free](https://render.com/docs/free) sleeps after 15 idle minutes and its
free PostgreSQL expires after 30 days. Keep anything needed before expiry. Disks
are ephemeral. Configuration follows the [Blueprint reference](https://render.com/docs/blueprint-spec).
