# ADR-0004: X bookmark write compatibility and 404 classification

Status: Accepted — 2026-10-10

## Incident

Discovery candidates render, but clicking 'bookmark' returns
`X CreateBookmark 返回非 JSON (HTTP 404)`. This is **X's upstream status**,
not a missing `/api/bookmark/toggle` route. The older adapter sent
`{"variables":{"tweet_id":"..."}}` only. Public references for the
web mutation include a top-level `queryId`, and the community registry
is known to rotate or lag real X client deployments.

A blank HTTP 404 can additionally mean X rejected a guarded GraphQL request
without a current `x-client-transaction-id`, not merely a stale operation ID.
We have NOT established that this guard is required by CreateBookmark.

## Decision

1. Add the required web GraphQL POST `queryId` envelope for both create/delete.
2. Resolve CreateBookmark/DeleteBookmark separately from the public upstream
   operation registry with reviewed config fallback; validate operation name,
   path, method and variable schema. Try the fallback only after a definite 404.
3. Return explicit diagnostic errors for 404/401/403/429/non-JSON or empty
   responses; **never pretend a failed write is saved**.
4. Preserve `Discovery -> saved_pending -> X sync/read-back -> saved`.
5. Keep X credentials in the existing private secret store. Never put them into
   CI/Issues, and do not forge a transaction ID or use a static one.
6. Include credential-free contract tests in `pnpm run check`.
7. Do not equate deployment success with an authenticated end-to-end X test.

## Remaining external constraint

Private X GraphQL endpoints are unsupported and may demand rotating,
session-bound browser signing or additional anti-abuse headers. The open-source
registry can remain unchanged while requests stop working. If a 404 persists
after the envelope/operation resolution fix, collect redacted status,
operation and content-type data and verify the current browser call in DevTools.
A supported long-term integration is the official X API v2 Bookmarks write
endpoint with user-scoped OAuth, if available to the account; that uses a
*different* authentication contract from the existing `auth_token` cookie.

References:
- https://github.com/fa0311/twitter-openapi
- https://github.com/mudrii/gobird/blob/main/docs/wire-protocol.md
- https://github.com/ichioda/x-client-transaction-id
- https://docs.x.com/x-api/posts/bookmarks/introduction
