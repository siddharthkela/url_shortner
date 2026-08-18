package com.urlshortener.service;

import com.urlshortener.dto.AnalyticsResponse;
import com.urlshortener.dto.CreateUrlRequest;
import com.urlshortener.dto.UpdateUrlRequest;
import com.urlshortener.dto.UrlResponse;
import com.urlshortener.entity.ShortUrlEntity;
import com.urlshortener.exception.AliasAlreadyExistsException;
import com.urlshortener.exception.InvalidUrlException;
import com.urlshortener.exception.TooManyActiveUrlsException;
import com.urlshortener.exception.UnauthorizedOwnerException;
import com.urlshortener.exception.UrlExpiredException;
import com.urlshortener.exception.UrlNotFoundException;
import com.urlshortener.mapper.UrlMapper;
import com.urlshortener.repository.ShortUrlRepository;
import com.urlshortener.util.Base62Encoder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class UrlService {

    private final ShortUrlRepository repository;
    private final long maxActiveUrls;
    private final String baseUrl;

    /**
     * In-memory idempotency store: no separate TTL/eviction, since the whole
     * dataset is already ephemeral (JVM-lifetime only) per the plan's design.
     */
    private final Map<String, UrlResponse> idempotencyCache = new ConcurrentHashMap<>();

    public UrlService(ShortUrlRepository repository,
                       @Value("${app.max-active-urls}") long maxActiveUrls,
                       @Value("${app.base-url}") String baseUrl) {
        this.repository = repository;
        this.maxActiveUrls = maxActiveUrls;
        this.baseUrl = baseUrl;
    }

    /**
     * Test-convenience overload only (package-private): self-invocation bypasses the
     * Spring proxy, so callers that need the @Transactional guarantee must call the
     * two-arg overload directly, as the controller does.
     */
    UrlResponse createShortUrl(CreateUrlRequest request) {
        return createShortUrl(request, null);
    }

    @Transactional
    public UrlResponse createShortUrl(CreateUrlRequest request, String idempotencyKey) {
        boolean hasIdempotencyKey = idempotencyKey != null && !idempotencyKey.isBlank();
        if (hasIdempotencyKey) {
            UrlResponse cached = idempotencyCache.get(idempotencyKey);
            if (cached != null) {
                return cached;
            }
        }

        UrlResponse response = persistShortUrl(request);

        if (hasIdempotencyKey) {
            idempotencyCache.put(idempotencyKey, response);
        }
        return response;
    }

    private UrlResponse persistShortUrl(CreateUrlRequest request) {
        validateOriginalUrl(request.originalUrl());
        validateExpiresAt(request.expiresAt());

        if (repository.countByActiveTrue() >= maxActiveUrls) {
            throw new TooManyActiveUrlsException("Maximum number of active short URLs reached");
        }

        UUID ownerToken = UUID.randomUUID();
        Instant now = Instant.now();
        boolean hasCustomAlias = request.customAlias() != null && !request.customAlias().isBlank();

        ShortUrlEntity entity;
        if (hasCustomAlias) {
            String alias = request.customAlias();
            if (repository.existsByShortCode(alias)) {
                throw new AliasAlreadyExistsException("Alias '" + alias + "' is already taken");
            }
            entity = new ShortUrlEntity(alias, request.originalUrl(), true, ownerToken, now, request.expiresAt());
            entity = repository.save(entity);
        } else {
            String placeholder = UUID.randomUUID().toString().substring(0, 16);
            entity = new ShortUrlEntity(placeholder, request.originalUrl(), false, ownerToken, now, request.expiresAt());
            entity = repository.save(entity);
            entity.setShortCode(Base62Encoder.encode(entity.getId()));
            entity = repository.save(entity);
        }

        return UrlMapper.toResponse(entity, baseUrl);
    }

    public UrlResponse getDetails(String shortCode) {
        ShortUrlEntity entity = findActiveOrThrow(shortCode);
        return UrlMapper.toResponse(entity, baseUrl);
    }

    @Transactional
    public String resolve(String shortCode) {
        ShortUrlEntity entity = findActiveOrThrow(shortCode);
        repository.incrementClickCount(shortCode, Instant.now());
        return entity.getOriginalUrl();
    }

    public AnalyticsResponse getAnalytics(String shortCode) {
        ShortUrlEntity entity = findActiveOrThrow(shortCode);
        return UrlMapper.toAnalyticsResponse(entity);
    }

    @Transactional
    public UrlResponse updateUrl(String shortCode, String ownerTokenHeader, UpdateUrlRequest request) {
        ShortUrlEntity entity = findOwnedActiveOrThrow(shortCode, ownerTokenHeader);

        if (request.originalUrl() != null && !request.originalUrl().isBlank()) {
            validateOriginalUrl(request.originalUrl());
            entity.setOriginalUrl(request.originalUrl());
        }
        if (request.expiresAt() != null) {
            validateExpiresAt(request.expiresAt());
            entity.setExpiresAt(request.expiresAt());
        }

        entity = repository.save(entity);
        return UrlMapper.toResponse(entity, baseUrl);
    }

    @Transactional
    public void deleteUrl(String shortCode, String ownerTokenHeader) {
        ShortUrlEntity entity = findOwnedActiveOrThrow(shortCode, ownerTokenHeader);
        entity.setActive(false);
        repository.save(entity);
    }

    /**
     * Read-path lookup (redirect, details, analytics): active row required, and
     * a past expiresAt yields 410 Gone rather than 404 Not Found, per Section 1.
     */
    private ShortUrlEntity findActiveOrThrow(String shortCode) {
        ShortUrlEntity entity = repository.findByShortCode(shortCode)
                .filter(ShortUrlEntity::isActive)
                .orElseThrow(() -> new UrlNotFoundException("Short code not found: " + shortCode));
        if (entity.getExpiresAt() != null && entity.getExpiresAt().isBefore(Instant.now())) {
            throw new UrlExpiredException("Short code has expired: " + shortCode);
        }
        return entity;
    }

    /**
     * Owner-mutation lookup (update, delete): no expiry check — an owner must be able
     * to extend or delete an already-expired URL. Not-found and wrong-owner both map
     * to distinct status codes (404 / 403) per Section 7.
     */
    private ShortUrlEntity findOwnedActiveOrThrow(String shortCode, String ownerTokenHeader) {
        ShortUrlEntity entity = repository.findByShortCode(shortCode)
                .filter(ShortUrlEntity::isActive)
                .orElseThrow(() -> new UrlNotFoundException("Short code not found: " + shortCode));
        UUID ownerToken = parseOwnerToken(ownerTokenHeader);
        if (!entity.getOwnerToken().equals(ownerToken)) {
            throw new UnauthorizedOwnerException("Owner token does not match");
        }
        return entity;
    }

    private UUID parseOwnerToken(String ownerTokenHeader) {
        try {
            return UUID.fromString(ownerTokenHeader);
        } catch (Exception e) {
            throw new UnauthorizedOwnerException("Missing or invalid owner token");
        }
    }

    private void validateOriginalUrl(String url) {
        URI uri;
        try {
            uri = new URI(url);
        } catch (URISyntaxException e) {
            throw new InvalidUrlException("Malformed URL: " + url);
        }
        String scheme = uri.getScheme();
        if (scheme == null || !(scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https"))) {
            throw new InvalidUrlException("URL must use http or https scheme: " + url);
        }
        if (uri.getHost() == null) {
            throw new InvalidUrlException("Malformed URL: " + url);
        }
    }

    private void validateExpiresAt(Instant expiresAt) {
        if (expiresAt != null && expiresAt.isBefore(Instant.now())) {
            throw new InvalidUrlException("expiresAt must be in the future");
        }
    }
}
