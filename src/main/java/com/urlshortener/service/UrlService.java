package com.urlshortener.service;

import com.urlshortener.util.Base62Encoder;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Phase 1: in-memory storage only, to prove the create/redirect flow end to end.
 * Replaced with JPA-backed persistence in Phase 2.
 */
@Service
public class UrlService {

    private final Map<String, String> shortCodeToUrl = new ConcurrentHashMap<>();
    private final AtomicLong idSequence = new AtomicLong(1);

    public String createShortUrl(String originalUrl) {
        long id = idSequence.getAndIncrement();
        String shortCode = Base62Encoder.encode(id);
        shortCodeToUrl.put(shortCode, originalUrl);
        return shortCode;
    }

    public Optional<String> resolve(String shortCode) {
        return Optional.ofNullable(shortCodeToUrl.get(shortCode));
    }
}
