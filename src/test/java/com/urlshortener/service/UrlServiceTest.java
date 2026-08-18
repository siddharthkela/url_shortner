package com.urlshortener.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.HashSet;
import java.util.Optional;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class UrlServiceTest {

    private UrlService urlService;

    @BeforeEach
    void setUp() {
        urlService = new UrlService();
    }

    @Test
    void createReturnsAShortCode() {
        String shortCode = urlService.createShortUrl("https://example.com/page");
        assertThat(shortCode).isNotBlank();
    }

    @Test
    void createdShortCodeResolvesToOriginalUrl() {
        String shortCode = urlService.createShortUrl("https://example.com/page");
        assertThat(urlService.resolve(shortCode)).contains("https://example.com/page");
    }

    @Test
    void distinctSubmissionsGetDistinctShortCodes() {
        String first = urlService.createShortUrl("https://example.com/one");
        String second = urlService.createShortUrl("https://example.com/two");
        assertThat(first).isNotEqualTo(second);
    }

    @Test
    void manyConcurrentCreatesProduceUniqueCodes() {
        Set<String> codes = new HashSet<>();
        for (int i = 0; i < 1000; i++) {
            codes.add(urlService.createShortUrl("https://example.com/" + i));
        }
        assertThat(codes).hasSize(1000);
    }

    @Test
    void resolvingUnknownCodeReturnsEmpty() {
        Optional<String> result = urlService.resolve("doesNotExist");
        assertThat(result).isEmpty();
    }
}
