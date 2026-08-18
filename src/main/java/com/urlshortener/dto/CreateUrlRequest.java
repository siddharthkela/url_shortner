package com.urlshortener.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.time.Instant;

public record CreateUrlRequest(
        @NotBlank(message = "originalUrl must not be blank")
        @Size(max = 2048, message = "originalUrl must be at most 2048 characters")
        String originalUrl,

        @Pattern(regexp = "^[a-zA-Z0-9_-]{3,16}$", message = "customAlias must be 3-16 alphanumeric/underscore/hyphen characters")
        String customAlias,

        Instant expiresAt
) {
}
