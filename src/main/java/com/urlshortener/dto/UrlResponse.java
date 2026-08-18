package com.urlshortener.dto;

public record UrlResponse(String shortCode, String shortUrl, String originalUrl) {
}
