package com.urlshortener.dto;

import java.time.Instant;

public record AnalyticsResponse(
        String shortCode,
        long clickCount,
        Instant firstAccessedAt,
        Instant lastAccessedAt
) {
}
