# ADR-0003: X-confirmed bookmark conversion

Date: 2026-10-10
Status: Accepted for feature/discovery-verified-x-bookmark

## Decision

The Discovery footer exposes Copy / Not Interested / Original, with a separate
corner × for false-positive discovery candidates. The reader removes the X
mutation button and offers Not Interested only for active Discovery entries.
Users bookmark directly in X, on any device. Xcollect does not interpret a
link click as a bookmark.

X Bookmarks sync remains authoritative for durable knowledge. Once X actually
returns a Tweet ID, xcollect persists the tweet, completes a D1 readback, then
joins that verified membership to eligible Discovery provenance. The server
appends one `bookmark` feedback event (idempotent by Tweet ID/action), preserving
the existing self-calibrated learning action ordering, with no fixed +1/+10/+50
weights. `open_original` remains a weaker precursor; the existing calibration
can learn whether such opens tend to convert.

The public `/api/feedback` endpoint rejects `bookmark` and `unbookmark`
client actions so that a proxy click cannot masquerade as confirmed membership.
Existing mutation endpoints are retained temporarily for backward compatibility,
but the frontend does not invoke them.

Only returned X IDs prove presence; an incomplete scan proves no absences.
Non-bookmarked Discovery candidates and their ephemeral evidence still expire
after 24h source age. A later X sync can still archive a genuine bookmark, but
cannot fabricate a conversion from deleted Discovery provenance. Learning failure
must never roll back a successful X -> D1 bookmark synchronization.

## Verification

- No active frontend bookmark mutation buttons or handler
- Authenticated X -> D1 sync produces terminal evidence only on membership
- Repeated sync does not multiply the conversion
- Opening original does not produce bookmark evidence
- Discovery TTL and semantic negative/false-positive signals are unchanged
