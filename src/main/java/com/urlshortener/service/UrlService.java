package com.urlshortener.service;

import com.urlshortener.dto.AnalyticsResponse;
import com.urlshortener.dto.CreateUrlRequest;
import com.urlshortener.dto.UrlResponse;
import com.urlshortener.entity.ShortUrlEntity;
import com.urlshortener.exception.AliasAlreadyExistsException;
import com.urlshortener.exception.InvalidUrlException;
import com.urlshortener.exception.TooManyActiveUrlsException;
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
import java.util.UUID;

@Service
public class UrlService {

    private final ShortUrlRepository repository;
    private final long maxActiveUrls;
    private final String baseUrl;

    public UrlService(ShortUrlRepository repository,
                       @Value("${app.max-active-urls}") long maxActiveUrls,
                       @Value("${app.base-url}") String baseUrl) {
        this.repository = repository;
        this.maxActiveUrls = maxActiveUrls;
        this.baseUrl = baseUrl;
    }

    @Transactional
    public UrlResponse createShortUrl(CreateUrlRequest request) {
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

    private ShortUrlEntity findActiveOrThrow(String shortCode) {
        return repository.findByShortCode(shortCode)
                .filter(ShortUrlEntity::isActive)
                .orElseThrow(() -> new UrlNotFoundException("Short code not found: " + shortCode));
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
