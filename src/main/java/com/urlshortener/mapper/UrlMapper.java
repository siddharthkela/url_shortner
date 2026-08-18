package com.urlshortener.mapper;

import com.urlshortener.dto.AnalyticsResponse;
import com.urlshortener.dto.UrlResponse;
import com.urlshortener.entity.ShortUrlEntity;

import java.time.Duration;
import java.time.Instant;

public final class UrlMapper {

    private UrlMapper() {
    }

    public static UrlResponse toResponse(ShortUrlEntity entity, String baseUrl) {
        return new UrlResponse(
                entity.getShortCode(),
                baseUrl + "/" + entity.getShortCode(),
                entity.getOriginalUrl(),
                entity.getOwnerToken().toString(),
                entity.getCreatedAt(),
                entity.getExpiresAt(),
                entity.isActive()
        );
    }

    public static AnalyticsResponse toAnalyticsResponse(ShortUrlEntity entity) {
        long daysActive = Math.max(1, Duration.between(entity.getCreatedAt(), Instant.now()).toDays());
        double averageClicksPerDay = entity.getClickCount() / (double) daysActive;
        return new AnalyticsResponse(
                entity.getShortCode(),
                entity.getClickCount(),
                entity.getFirstAccessedAt(),
                entity.getLastAccessedAt(),
                daysActive,
                averageClicksPerDay
        );
    }
}
