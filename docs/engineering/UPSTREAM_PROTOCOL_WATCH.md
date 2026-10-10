# X / Twitter upstream protocol monitoring

## References and scope

The exploration landscape in `docs/research/EXPLORATION_TOOLS_LANDSCAPE.md` names
[sytelus/xarchive](https://github.com/sytelus/xarchive) and
[0x1b2c/twitter-bookmarks-downloader](https://github.com/0x1b2c/twitter-bookmarks-downloader)
as source acquisition references. The running Xcollect adapter also uses the
[fa0311/twitter-openapi](https://github.com/fa0311/twitter-openapi) operation registry.

This watch monitors five reviewed files:
- twitter-openapi: `src/config/placeholder.json` (operation IDs, verbs and sample variables);
- twitter-openapi: `src/openapi/paths/bookmarks.yaml` (timeline schema);
- xarchive: `lib/query-ids.js` (capturing IDs from requests/bundles);
- xarchive: `lib/api.js` (request headers, CSRF and GraphQL transport);
- twitter-bookmarks-downloader: `sync-bookmarks.user.js` (X page route changes and request capture).

See `scripts/upstream_sources.json` for the **reviewed blob SHA baseline** of each file.
Monitoring file contents (rather than only repository HEAD) reduces unrelated update noise.
Hashes do not automatically advance; a change stays visible until explicitly reviewed.

## Schedule and alerting

`.github/workflows/upstream-watch.yml` runs daily at **05:17 UTC**, on manual dispatch,
and when its own files/config change on `main`. PRs run offline tests only.
No X login/session cookie is provided to CI, and CI must never send a
CreateBookmark/DeleteBookmark request to an arbitrary tweet.

Every scan:
1. Fetches public upstream GitHub contents through GitHub's authenticated REST API;
2. validates returned blob hashes;
3. compares source content against reviewed SHA baselines;
4. compares registry `queryId`, path, HTTP verb and variable keys against `config.toml`;
5. emits a summary and 30-day JSON artifact;
6. creates/updates one deduplicated Issue on drift or network/check failure;
7. closes that Issue only after a fully clean scan.

Note: this is **static upstream contract monitoring**, not a proof that the
X private APIs still work. A stable but stale community registry can still be broken.
Production compatibility requires a separate **authorized authenticated** end-to-end
write -> bookmark sync -> ID read-back check, not an unattended CI action.
404/HTML, 401/403/CSRF, rate limiting and transport/schema failures should be
reported separately by the runtime adapter.

## Responding to a change

Read the automated Issue and upstream diff. Confirm whether the change
affects CreateBookmark, DeleteBookmark, Bookmarks, or SearchTimeline, or relevant
headers/bundle discovery. Update the X adapter and regression tests as needed.
Do not silently promote Discovery candidates: preserve the two-phase
`saved_pending -> synchronized bookmark -> saved` invariant.

After validation, replace only the reviewed file SHA(s) in
`scripts/upstream_sources.json` and merge through the ordinary checks.
The next clean scheduled/manual check resolves the Issue.

Local verification:

```bash
python -m unittest discover -s tests -p "test_watch_x_upstreams.py" -v
python scripts/watch_x_upstreams.py --output upstream-watch-report.json
```

The second command requires GitHub network access; optionally set `GITHUB_TOKEN`
for higher API limits. It does not use any X login credential.
