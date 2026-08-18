package com.urlshortener.dto;

import java.time.Instant;

public record UrlResponse(
        String shortCode,
        String shortUrl,
        String originalUrl,
        String ownerToken,
        Instant createdAt,
        Instant expiresAt,
        boolean active
) {
}
