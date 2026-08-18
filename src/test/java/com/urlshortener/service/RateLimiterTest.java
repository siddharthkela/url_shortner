package com.urlshortener.service;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class RateLimiterTest {

    @Test
    void allowsRequestsUpToTheLimit() {
        RateLimiter limiter = new RateLimiter(3, true);

        assertThat(limiter.tryAcquire("client-a")).isTrue();
        assertThat(limiter.tryAcquire("client-a")).isTrue();
        assertThat(limiter.tryAcquire("client-a")).isTrue();
    }

    @Test
    void rejectsRequestsBeyondTheLimit() {
        RateLimiter limiter = new RateLimiter(2, true);

        assertThat(limiter.tryAcquire("client-b")).isTrue();
        assertThat(limiter.tryAcquire("client-b")).isTrue();
        assertThat(limiter.tryAcquire("client-b")).isFalse();
    }

    @Test
    void tracksDifferentClientsIndependently() {
        RateLimiter limiter = new RateLimiter(1, true);

        assertThat(limiter.tryAcquire("client-c")).isTrue();
        assertThat(limiter.tryAcquire("client-d")).isTrue();
    }

    @Test
    void allowsUnlimitedRequestsWhenDisabled() {
        RateLimiter limiter = new RateLimiter(1, false);

        assertThat(limiter.tryAcquire("client-e")).isTrue();
        assertThat(limiter.tryAcquire("client-e")).isTrue();
        assertThat(limiter.tryAcquire("client-e")).isTrue();
    }
}
