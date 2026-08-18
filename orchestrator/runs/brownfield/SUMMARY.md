# Run summary: Brownfield: rate limiting on URL creation

**Requirement:** Add rate limiting to URL creation to prevent abuse.
**Branch:** `orchestrator-demo/brownfield-rate-limit`
**Run ID:** brownfield-rate-limit

## Decision lineage

1. **requirements** — Normalized: Reject URL-creation requests beyond a configurable per-client rate, returning 429, before they reach persistence.
   - *Rationale:* Clear abuse-prevention requirement with an obvious existing pattern (app.max-active-urls' 429) to extend rather than reinvent.
2. **codebase_analysis** — Impacted (existing): ['src/main/java/com/urlshortener/controller/UrlController.java', 'src/main/resources/application.yml', 'src/main/java/com/urlshortener/exception/GlobalExceptionHandler.java']; new: ['src/main/java/com/urlshortener/service/RateLimiter.java', 'src/main/java/com/urlshortener/exception/RateLimitExceededException.java']
   - *Rationale:* Actually read UrlController.java and GlobalExceptionHandler.java to confirm the create endpoint and the existing 429-mapping pattern exist before designing around them, rather than assuming.
3. **design** — Approach: New RateLimiter @Component: fixed per-minute window, ConcurrentHashMap<clientKey, Window>, no external dependency (no Redis — consistent with the whole app's no-external-infra design). Checked in UrlController.createShortUrl before delegating to UrlService.
   - *Rationale:* In-memory + no new dependency matches this app's established single-instance, no-external-infra architecture (see the original engineering plan's rationale for dropping Redis) rather than introducing a new pattern.
4. **implementation** — Wrote/modified: ['src/main/java/com/urlshortener/exception/RateLimitExceededException.java', 'src/main/java/com/urlshortener/service/RateLimiter.java', 'src/main/java/com/urlshortener/controller/UrlController.java', 'src/main/java/com/urlshortener/exception/GlobalExceptionHandler.java', 'src/main/resources/application.yml']
   - *Rationale:* 
5. **test** — Wrote/modified: ['src/test/java/com/urlshortener/service/RateLimiterTest.java', 'src/test/java/com/urlshortener/controller/UrlControllerTest.java']
   - *Rationale:* 
6. **docs** — Wrote: ['README.md']
   - *Rationale:* 
7. **approval** — Approved node 'release_readiness'
   - *Rationale:* autonomy=assisted, requires_approval=True
8. **release** — Release status: ready
   - *Rationale:* 

## Reliability metrics

| Metric | Value |
|---|---|
| Success rate | 100% (10/10 nodes) |
| Retries | 1 |
| Rollbacks | 0 |
| MTTR | 10.10s |
| Total latency | 11.70s |

## Risks & trade-offs

- The rate limiter is in-memory per-instance; since the app is explicitly single-instance (per the engineering plan), this is consistent with the existing architecture rather than a new limitation.
- Keying by remote IP address means users behind a shared NAT/proxy share a limit — acceptable for an abuse-prevention safety valve, not precise per-user throttling.
- State resets on restart along with everything else in this app (by design) — not a new durability concern specific to this feature.

## Assumptions

- Rate limiting applies only to POST /api/v1/urls (creation) — the abuse vector named in the requirement — not to redirects/reads, which have no cost-of-abuse concern of the same kind.
- A fixed per-minute window is sufficient; the requirement didn't specify burst tolerance that would justify a more complex token-bucket-with-burst design.

## Limitations

- No per-owner-token limiting (only per-IP), since ownerToken doesn't exist until after creation succeeds — a future iteration could add a second limiter keyed on ownerToken for update/delete abuse specifically.
