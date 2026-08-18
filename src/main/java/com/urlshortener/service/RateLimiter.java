package com.urlshortener.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Fixed per-minute window, keyed per client. In-memory only, consistent with
 * this app's single-instance, no-external-infra architecture (see the
 * engineering plan's rationale for dropping Redis) — a distributed rate
 * limiter is out of scope for the same reason a shared cache was ruled out.
 */
@Component
public class RateLimiter {

    private final int requestsPerMinute;
    private final boolean enabled;
    private final ConcurrentHashMap<String, Window> windows = new ConcurrentHashMap<>();

    public RateLimiter(@Value("${app.rate-limit.requests-per-minute}") int requestsPerMinute,
                        @Value("${app.rate-limit.enabled}") boolean enabled) {
        this.requestsPerMinute = requestsPerMinute;
        this.enabled = enabled;
    }

    public boolean tryAcquire(String clientKey) {
        if (!enabled) {
            return true;
        }
        long currentMinute = Instant.now().getEpochSecond() / 60;
        Window window = windows.compute(clientKey, (key, existing) ->
                (existing == null || existing.minute != currentMinute) ? new Window(currentMinute) : existing);
        return window.count.incrementAndGet() <= requestsPerMinute;
    }

    private static final class Window {
        final long minute;
        final AtomicInteger count = new AtomicInteger(0);

        Window(long minute) {
            this.minute = minute;
        }
    }
}
