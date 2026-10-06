# Shared-login bridge review

Reviewed demo implementation: Helios `267c619`, Next.js `f26af8d`.

| Threat | Enforced control | Validation |
| --- | --- | --- |
| Login forgery | Server SDK validates the current Neon session with cookie-cache bypass; signed Helios requests and authenticated HTTPS redemption | Invalid signature, missing session, ineligible account, missing exchange authentication rejected |
| Account substitution | Stable managed user ID; matching managed session user ID; verified exact domain; current email and session rechecked at redemption; no email-based linking | Browser identity fields ignored; changed email, substituted session subject and revoked session rejected |
| Replay/concurrent redemption | Random 256-bit code, SHA-256 storage, max 60-second expiry; single PostgreSQL DELETE RETURNING; independently locked/consumed Helios browser request | Concurrent PostgreSQL requests produce exactly one winner; replay and expiry rejected |
| Login CSRF | Signed state/PKCE request; Helios session-key hash; exact Origin and existing custom CSRF checks; session and CSRF rotation | Wrong state, Origin, CSRF and browser session rejected |
| Open redirect | Exact configured HTTPS origins/callback; server-selected fixed local election return paths; redirect following disabled on exchange | Signed attacker callback rejected; client also checks fixed destination |
| Unauthorized election access | Election/client/PKCE/state binding, explicit allowlists in both apps, independent Helios enrollment/private-election checks | Wrong-election redemption/view, closed registration and private enrollment rejected |
| Privilege escalation | No role inputs/claims in browser protocol; new Helios users have no admin flag; existing role checks remain server-side | Student tally request returns 403; existing explicit admin grant preserved; bootstrap grants one election only |
| Credential disclosure | Fragments plus POST bodies; no-store/no-referrer; no request/body/token exception logging; credentials only server environment; grant table RLS with no browser policies | Migration applied in Neon and no browser policies present; no secrets committed |

228 Helios tests passed. 28 frontend security checks passed against isolated real
PostgreSQL. A cross-language integration test used Python-signed requests and the
production TypeScript authorization/exchange handlers, then real Helios encryption,
automatic voter registration, proof verification, closing and synchronous trustee
tallying. Only the managed Auth network session was a trusted fixture; no fake Auth
schema was created in Neon. Clean frontend production build passed. Next.js runtime
was patched from 16.3.4 to 16.3.8 following its dependency advisory.
The transitive source-map-js runtime dependency was patched to 1.2.2; the final
runtime-only npm audit reports zero advisories.

Remaining practical limits:

- Live browser login, real booth interaction, hosted HTTPS exchange, and Render
  Docker startup remain deployment checks; local tests do not prove them.
- The bridge trusts Neon Auth and both servers plus the shared secret. This is a
  reviewed custom demo protocol, not an independent security audit.
- Managed-session revocation after successful exchange takes up to five minutes
  to invalidate the Helios session. Committee role changes continue to follow
  each application's server-side role checks; the bridge does not synchronize
  or automatically grant Helios administrator roles.
- Browser XSS or compromised app/deployment credentials defeats the corresponding
  identity boundary. Do not enable request-body/header capture in hosting logs.
- One free web worker and synchronous cryptography limit availability. Session
  throttling is small-demo protection, not a distributed abuse-control system.
- A single Helios trustee and temporary Free PostgreSQL are demo choices, not
  production election governance or durable hosting.
- npm reports development-tool advisories in the existing ESLint dependency tree;
  the patched Next.js runtime has no reported runtime advisory in that audit.
