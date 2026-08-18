package com.urlshortener.dto;

import jakarta.validation.constraints.Size;

import java.time.Instant;

public record UpdateUrlRequest(
        @Size(max = 2048, message = "originalUrl must be at most 2048 characters")
        String originalUrl,

        Instant expiresAt
) {
}
