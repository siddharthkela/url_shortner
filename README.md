# URL Shortener

A single-instance URL shortener service. Spring Boot 3.3.5, Java 21, Spring Data
JPA on H2 running **embedded, in-memory** — there is no external database or
cache. All data lives only as long as the JVM process runs; a restart wipes
every short URL. That's a deliberate design choice, not a bug — see the
engineering plan this project was built from for the full rationale.

## Requirements

- Java 21 (only if running without Docker — the Maven Wrapper handles Maven itself)
- Docker + Docker Compose (only if running via Docker)

## Run locally

```bash
./mvnw spring-boot:run
```

The app starts on `http://localhost:8080`.

## Run the tests

```bash
./mvnw test
```

This runs the full suite: unit tests, `@DataJpaTest` repository tests against
real H2, a concurrency test that proves the atomic click-count update has no
lost updates under load, and full-lifecycle integration tests against a real
running Spring context. No Docker daemon or external services are needed to
run the tests — H2 in-memory is the actual datastore, not a test substitute.

## Run via Docker

```bash
docker compose up --build
```

The app is then available on `http://localhost:8080`. Stop it with:

```bash
docker compose down
```

## API

All endpoints are under `/api/v1/urls` except the redirect itself.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/urls` | Create a short URL. Optional `Idempotency-Key` header. |
| `GET` | `/{shortCode}` | Redirects (`302`) to the original URL. `404` if unknown, `410` if expired. |
| `GET` | `/api/v1/urls/{shortCode}` | Fetch details. |
| `GET` | `/api/v1/urls/{shortCode}/analytics` | Click count, first/last accessed timestamps. |
| `PUT` | `/api/v1/urls/{shortCode}` | Update target URL / expiration. Requires `X-Owner-Token` header. |
| `DELETE` | `/api/v1/urls/{shortCode}` | Soft delete. Requires `X-Owner-Token` header. |

### Example: create and use a short URL

```bash
# Create
curl -s -X POST http://localhost:8080/api/v1/urls \
  -H 'Content-Type: application/json' \
  -d '{"originalUrl": "https://example.com/some/long/path"}'
# -> {"shortCode":"1","shortUrl":"http://localhost:8080/1","originalUrl":"...","ownerToken":"...","createdAt":"...","expiresAt":null,"active":true}

# Follow the short link (302 redirect)
curl -i http://localhost:8080/1

# Check analytics after a few redirects
curl -s http://localhost:8080/api/v1/urls/1/analytics

# Update (requires the ownerToken returned at creation)
curl -s -X PUT http://localhost:8080/api/v1/urls/1 \
  -H 'Content-Type: application/json' \
  -H 'X-Owner-Token: <ownerToken>' \
  -d '{"originalUrl": "https://example.com/new-target"}'

# Delete (soft delete)
curl -s -X DELETE http://localhost:8080/api/v1/urls/1 \
  -H 'X-Owner-Token: <ownerToken>'
```

### Custom alias

```bash
curl -s -X POST http://localhost:8080/api/v1/urls \
  -H 'Content-Type: application/json' \
  -d '{"originalUrl": "https://example.com", "customAlias": "my-alias"}'
```

### Observability

- `GET /actuator/health`, `/actuator/info`, `/actuator/metrics`
- Every request/response carries an `X-Correlation-Id` header (generated if not
  supplied), and it appears in every log line for that request.

## What's intentionally not included

- **Load testing** (Section 19, Phase 10 of the engineering plan) — needs
  external tooling (k6/Gatling) and isn't needed to prove correctness of this
  build.
- **A general-purpose rate limiter** — the plan only specifies a hard cap on
  total active URLs (`app.max-active-urls`, returns `429` when exceeded) as
  the heap-exhaustion safety valve; it doesn't specify request-rate thresholds
  to build a limiter against.

## Architecture notes

- Single instance only — H2 in-memory is local to one JVM, so this cannot be
  horizontally scaled. Running multiple instances would give each one an
  independent, inconsistent dataset.
- No durability — a restart, crash, or redeploy loses all data. Suitable for
  prototyping/demos, not for links that need to survive a deploy.
