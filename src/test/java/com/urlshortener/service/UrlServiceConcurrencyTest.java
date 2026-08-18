package com.urlshortener.service;

import com.urlshortener.dto.AnalyticsResponse;
import com.urlshortener.dto.CreateUrlRequest;
import com.urlshortener.dto.UrlResponse;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Proves Section 9's claim: a single "SET clickCount = clickCount + 1" bulk UPDATE
 * is safe under concurrent redirects, with no lost updates — the pattern that a
 * naive read-modify-write in Java would get wrong.
 */
@SpringBootTest
class UrlServiceConcurrencyTest {

    @org.springframework.beans.factory.annotation.Autowired
    private UrlService urlService;

    @Test
    void concurrentRedirectsProduceExactClickCountWithNoLostUpdates() throws InterruptedException {
        UrlResponse created = urlService.createShortUrl(new CreateUrlRequest("https://example.com/concurrency", null, null));
        String shortCode = created.shortCode();

        int threadCount = 50;
        ExecutorService executor = Executors.newFixedThreadPool(threadCount);
        CountDownLatch startLatch = new CountDownLatch(1);
        CountDownLatch doneLatch = new CountDownLatch(threadCount);

        for (int i = 0; i < threadCount; i++) {
            executor.submit(() -> {
                try {
                    startLatch.await();
                    urlService.resolve(shortCode);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } finally {
                    doneLatch.countDown();
                }
            });
        }

        startLatch.countDown();
        boolean completed = doneLatch.await(30, TimeUnit.SECONDS);
        executor.shutdown();

        assertThat(completed).isTrue();

        AnalyticsResponse analytics = urlService.getAnalytics(shortCode);
        assertThat(analytics.clickCount()).isEqualTo(threadCount);
    }
}
