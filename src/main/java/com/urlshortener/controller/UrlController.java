package com.urlshortener.controller;

import com.urlshortener.dto.AnalyticsResponse;
import com.urlshortener.dto.CreateUrlRequest;
import com.urlshortener.dto.UpdateUrlRequest;
import com.urlshortener.dto.UrlResponse;
import com.urlshortener.service.UrlService;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public class UrlController {

    private final UrlService urlService;

    public UrlController(UrlService urlService) {
        this.urlService = urlService;
    }

    @PostMapping("/api/v1/urls")
    public ResponseEntity<UrlResponse> createShortUrl(@Valid @RequestBody CreateUrlRequest request,
                                                        @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey) {
        UrlResponse response = urlService.createShortUrl(request, idempotencyKey);
        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }

    @GetMapping("/{shortCode}")
    public ResponseEntity<Void> redirect(@PathVariable String shortCode) {
        String originalUrl = urlService.resolve(shortCode);
        return ResponseEntity.status(HttpStatus.FOUND)
                .header(HttpHeaders.LOCATION, originalUrl)
                .build();
    }

    @GetMapping("/api/v1/urls/{shortCode}")
    public ResponseEntity<UrlResponse> getDetails(@PathVariable String shortCode) {
        return ResponseEntity.ok(urlService.getDetails(shortCode));
    }

    @GetMapping("/api/v1/urls/{shortCode}/analytics")
    public ResponseEntity<AnalyticsResponse> getAnalytics(@PathVariable String shortCode) {
        return ResponseEntity.ok(urlService.getAnalytics(shortCode));
    }

    @PutMapping("/api/v1/urls/{shortCode}")
    public ResponseEntity<UrlResponse> updateUrl(@PathVariable String shortCode,
                                                  @RequestHeader(value = "X-Owner-Token", required = false) String ownerToken,
                                                  @Valid @RequestBody UpdateUrlRequest request) {
        return ResponseEntity.ok(urlService.updateUrl(shortCode, ownerToken, request));
    }

    @DeleteMapping("/api/v1/urls/{shortCode}")
    public ResponseEntity<Void> deleteUrl(@PathVariable String shortCode,
                                          @RequestHeader(value = "X-Owner-Token", required = false) String ownerToken) {
        urlService.deleteUrl(shortCode, ownerToken);
        return ResponseEntity.noContent().build();
    }
}
