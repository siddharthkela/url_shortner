package com.urlshortener.mapper;

import com.urlshortener.dto.AnalyticsResponse;
import com.urlshortener.dto.UrlResponse;
import com.urlshortener.entity.ShortUrlEntity;

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
        return new AnalyticsResponse(
                entity.getShortCode(),
                entity.getClickCount(),
                entity.getFirstAccessedAt(),
                entity.getLastAccessedAt()
        );
    }
}
