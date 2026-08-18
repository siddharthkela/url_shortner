package com.urlshortener.integration;

import com.urlshortener.dto.AnalyticsResponse;
import com.urlshortener.dto.UrlResponse;
import com.urlshortener.repository.ShortUrlRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Full lifecycle against a real, running Spring context: create -> details ->
 * redirect (counted) -> analytics reflects it -> update -> expire -> delete ->
 * 404 after delete. Also covers the Idempotency-Key retry path end to end.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class UrlShortenerIntegrationTest {

    @LocalServerPort
    private int port;

    @Autowired
    private ShortUrlRepository repository;

    private final TestRestTemplate restTemplate = nonFollowingRestTemplate();

    /**
     * TestRestTemplate (unlike plain RestTemplate) returns error responses as a
     * ResponseEntity instead of throwing, which is what lets these tests assert
     * 404/410/403 directly. The custom request factory additionally disables
     * redirect-following so a 302 can be asserted rather than transparently chased.
     */
    private static TestRestTemplate nonFollowingRestTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory() {
            @Override
            protected void prepareConnection(HttpURLConnection connection, String httpMethod) throws IOException {
                super.prepareConnection(connection, httpMethod);
                connection.setInstanceFollowRedirects(false);
            }
        };
        return new TestRestTemplate(new RestTemplateBuilder().requestFactory(() -> factory));
    }

    private String url(String path) {
        return "http://localhost:" + port + path;
    }

    @Test
    void fullLifecycle_createDetailsRedirectAnalyticsUpdateDeleteAndSubsequent404() {
        HttpHeaders jsonHeaders = new HttpHeaders();
        jsonHeaders.setContentType(MediaType.APPLICATION_JSON);

        ResponseEntity<UrlResponse> createResponse = restTemplate.postForEntity(
                url("/api/v1/urls"),
                new HttpEntity<>("{\"originalUrl\": \"https://example.com/lifecycle\"}", jsonHeaders),
                UrlResponse.class);
        assertThat(createResponse.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        UrlResponse created = createResponse.getBody();
        assertThat(created).isNotNull();
        String shortCode = created.shortCode();
        String ownerToken = created.ownerToken();

        ResponseEntity<UrlResponse> detailsResponse = restTemplate.getForEntity(
                url("/api/v1/urls/" + shortCode), UrlResponse.class);
        assertThat(detailsResponse.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(detailsResponse.getBody().originalUrl()).isEqualTo("https://example.com/lifecycle");

        ResponseEntity<Void> redirectResponse = restTemplate.exchange(
                url("/" + shortCode), HttpMethod.GET, HttpEntity.EMPTY, Void.class);
        assertThat(redirectResponse.getStatusCode()).isEqualTo(HttpStatus.FOUND);
        assertThat(redirectResponse.getHeaders().getLocation().toString()).isEqualTo("https://example.com/lifecycle");

        ResponseEntity<AnalyticsResponse> analyticsResponse = restTemplate.getForEntity(
                url("/api/v1/urls/" + shortCode + "/analytics"), AnalyticsResponse.class);
        assertThat(analyticsResponse.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(analyticsResponse.getBody().clickCount()).isEqualTo(1);

        HttpHeaders ownerJsonHeaders = new HttpHeaders();
        ownerJsonHeaders.setContentType(MediaType.APPLICATION_JSON);
        ownerJsonHeaders.set("X-Owner-Token", ownerToken);
        ResponseEntity<UrlResponse> updateResponse = restTemplate.exchange(
                url("/api/v1/urls/" + shortCode), HttpMethod.PUT,
                new HttpEntity<>("{\"originalUrl\": \"https://example.com/updated\"}", ownerJsonHeaders),
                UrlResponse.class);
        assertThat(updateResponse.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(updateResponse.getBody().originalUrl()).isEqualTo("https://example.com/updated");

        HttpHeaders ownerHeaders = new HttpHeaders();
        ownerHeaders.set("X-Owner-Token", ownerToken);
        ResponseEntity<Void> deleteResponse = restTemplate.exchange(
                url("/api/v1/urls/" + shortCode), HttpMethod.DELETE, new HttpEntity<>(ownerHeaders), Void.class);
        assertThat(deleteResponse.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);

        ResponseEntity<String> afterDelete = restTemplate.getForEntity(url("/api/v1/urls/" + shortCode), String.class);
        assertThat(afterDelete.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void expiredUrlReturns410OnRedirectAndDetails() throws InterruptedException {
        HttpHeaders jsonHeaders = new HttpHeaders();
        jsonHeaders.setContentType(MediaType.APPLICATION_JSON);
        String expiresAt = Instant.now().plusMillis(800).toString();

        ResponseEntity<UrlResponse> createResponse = restTemplate.postForEntity(
                url("/api/v1/urls"),
                new HttpEntity<>("{\"originalUrl\": \"https://example.com/expiring\", \"expiresAt\": \"" + expiresAt + "\"}", jsonHeaders),
                UrlResponse.class);
        assertThat(createResponse.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        String shortCode = createResponse.getBody().shortCode();

        Thread.sleep(1200);

        ResponseEntity<String> redirectResponse = restTemplate.getForEntity(url("/" + shortCode), String.class);
        assertThat(redirectResponse.getStatusCode()).isEqualTo(HttpStatus.GONE);

        ResponseEntity<String> detailsResponse = restTemplate.getForEntity(url("/api/v1/urls/" + shortCode), String.class);
        assertThat(detailsResponse.getStatusCode()).isEqualTo(HttpStatus.GONE);
    }

    @Test
    void retryingCreateWithSameIdempotencyKeyReturnsSameShortCodeWithoutDuplicateRow() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("Idempotency-Key", "integration-test-key-1");
        HttpEntity<String> request = new HttpEntity<>("{\"originalUrl\": \"https://example.com/idempotent\"}", headers);

        long countBefore = repository.count();

        ResponseEntity<UrlResponse> first = restTemplate.postForEntity(url("/api/v1/urls"), request, UrlResponse.class);
        ResponseEntity<UrlResponse> second = restTemplate.postForEntity(url("/api/v1/urls"), request, UrlResponse.class);

        assertThat(first.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(second.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(second.getBody().shortCode()).isEqualTo(first.getBody().shortCode());
        assertThat(repository.count()).isEqualTo(countBefore + 1);
    }
}
