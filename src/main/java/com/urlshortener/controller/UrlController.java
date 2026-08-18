package com.urlshortener.controller;

import com.urlshortener.dto.CreateUrlRequest;
import com.urlshortener.dto.UrlResponse;
import com.urlshortener.service.UrlService;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.net.URI;

@RestController
public class UrlController {

    private final UrlService urlService;

    public UrlController(UrlService urlService) {
        this.urlService = urlService;
    }

    @PostMapping("/api/v1/urls")
    public ResponseEntity<UrlResponse> createShortUrl(@RequestBody CreateUrlRequest request) {
        String shortCode = urlService.createShortUrl(request.originalUrl());
        UrlResponse response = new UrlResponse(shortCode, "/" + shortCode, request.originalUrl());
        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }

    @GetMapping("/{shortCode}")
    public ResponseEntity<Void> redirect(@PathVariable String shortCode) {
        return urlService.resolve(shortCode)
                .map(originalUrl -> ResponseEntity.status(HttpStatus.FOUND)
                        .header(HttpHeaders.LOCATION, URI.create(originalUrl).toString())
                        .<Void>build())
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
