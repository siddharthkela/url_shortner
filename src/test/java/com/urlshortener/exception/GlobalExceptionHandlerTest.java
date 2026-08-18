package com.urlshortener.exception;

import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;

import static org.assertj.core.api.Assertions.assertThat;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();
    private final MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/urls/abc123");

    @Test
    void mapsUrlNotFoundTo404() {
        ResponseEntity<?> response = handler.handleNotFound(new UrlNotFoundException("gone missing"), request);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void mapsUrlExpiredTo410() {
        ResponseEntity<?> response = handler.handleExpired(new UrlExpiredException("expired"), request);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.GONE);
    }

    @Test
    void mapsAliasAlreadyExistsTo409() {
        ResponseEntity<?> response = handler.handleAliasTaken(new AliasAlreadyExistsException("taken"), request);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
    }

    @Test
    void mapsDataIntegrityViolationTo409() {
        ResponseEntity<?> response = handler.handleDataIntegrityViolation(
                new DataIntegrityViolationException("unique violation"), request);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
    }

    @Test
    void mapsUnauthorizedOwnerTo403() {
        ResponseEntity<?> response = handler.handleUnauthorizedOwner(new UnauthorizedOwnerException("not yours"), request);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
    }

    @Test
    void mapsInvalidUrlTo400() {
        ResponseEntity<?> response = handler.handleInvalidUrl(new InvalidUrlException("bad url"), request);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }

    @Test
    void mapsTooManyActiveUrlsTo429() {
        ResponseEntity<?> response = handler.handleTooManyActiveUrls(new TooManyActiveUrlsException("cap reached"), request);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
    }

    @Test
    void mapsUnexpectedExceptionTo500WithoutLeakingDetails() {
        ResponseEntity<?> response = handler.handleUnexpected(new RuntimeException("secret internal detail"), request);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody().toString()).doesNotContain("secret internal detail");
    }
}
