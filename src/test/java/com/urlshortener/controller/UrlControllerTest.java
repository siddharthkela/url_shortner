package com.urlshortener.controller;

import com.urlshortener.dto.AnalyticsResponse;
import com.urlshortener.dto.UrlResponse;
import com.urlshortener.exception.AliasAlreadyExistsException;
import com.urlshortener.exception.TooManyActiveUrlsException;
import com.urlshortener.exception.UnauthorizedOwnerException;
import com.urlshortener.exception.UrlExpiredException;
import com.urlshortener.exception.UrlNotFoundException;
import com.urlshortener.service.UrlService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(UrlController.class)
class UrlControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private UrlService urlService;

    @Test
    void createReturns201OnValidRequest() throws Exception {
        UrlResponse response = new UrlResponse("abc123", "http://localhost:8080/abc123",
                "https://example.com", "owner-token", Instant.now(), null, true);
        when(urlService.createShortUrl(any(), any())).thenReturn(response);

        mockMvc.perform(post("/api/v1/urls")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"originalUrl\": \"https://example.com\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.shortCode").value("abc123"));
    }

    @Test
    void createReturns400OnBlankOriginalUrl() throws Exception {
        mockMvc.perform(post("/api/v1/urls")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"originalUrl\": \"\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void createReturns400OnInvalidCustomAliasPattern() throws Exception {
        mockMvc.perform(post("/api/v1/urls")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"originalUrl\": \"https://example.com\", \"customAlias\": \"a\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void createReturns409WhenAliasAlreadyTaken() throws Exception {
        when(urlService.createShortUrl(any(), any())).thenThrow(new AliasAlreadyExistsException("taken"));

        mockMvc.perform(post("/api/v1/urls")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"originalUrl\": \"https://example.com\", \"customAlias\": \"taken123\"}"))
                .andExpect(status().isConflict());
    }

    @Test
    void createReturns429WhenCapReached() throws Exception {
        when(urlService.createShortUrl(any(), any())).thenThrow(new TooManyActiveUrlsException("cap reached"));

        mockMvc.perform(post("/api/v1/urls")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"originalUrl\": \"https://example.com\"}"))
                .andExpect(status().isTooManyRequests());
    }

    @Test
    void redirectReturns302WhenFound() throws Exception {
        when(urlService.resolve("abc123")).thenReturn("https://example.com");

        mockMvc.perform(get("/abc123"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "https://example.com"));
    }

    @Test
    void redirectReturns404WhenNotFound() throws Exception {
        when(urlService.resolve("missing")).thenThrow(new UrlNotFoundException("not found"));

        mockMvc.perform(get("/missing"))
                .andExpect(status().isNotFound());
    }

    @Test
    void redirectReturns410WhenExpired() throws Exception {
        when(urlService.resolve("expired")).thenThrow(new UrlExpiredException("expired"));

        mockMvc.perform(get("/expired"))
                .andExpect(status().isGone());
    }

    @Test
    void getDetailsReturns200WhenFound() throws Exception {
        UrlResponse response = new UrlResponse("abc123", "http://localhost:8080/abc123",
                "https://example.com", "owner-token", Instant.now(), null, true);
        when(urlService.getDetails("abc123")).thenReturn(response);

        mockMvc.perform(get("/api/v1/urls/abc123"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.originalUrl").value("https://example.com"));
    }

    @Test
    void getDetailsReturns404WhenNotFound() throws Exception {
        when(urlService.getDetails("missing")).thenThrow(new UrlNotFoundException("not found"));

        mockMvc.perform(get("/api/v1/urls/missing"))
                .andExpect(status().isNotFound());
    }

    @Test
    void getAnalyticsReturns200WhenFound() throws Exception {
        AnalyticsResponse response = new AnalyticsResponse("abc123", 5, Instant.now(), Instant.now(), 3, 1.67);
        when(urlService.getAnalytics("abc123")).thenReturn(response);

        mockMvc.perform(get("/api/v1/urls/abc123/analytics"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.clickCount").value(5));
    }

    @Test
    void getAnalyticsReturns404WhenNotFound() throws Exception {
        when(urlService.getAnalytics("missing")).thenThrow(new UrlNotFoundException("not found"));

        mockMvc.perform(get("/api/v1/urls/missing/analytics"))
                .andExpect(status().isNotFound());
    }

    @Test
    void updateReturns200OnSuccess() throws Exception {
        UrlResponse response = new UrlResponse("abc123", "http://localhost:8080/abc123",
                "https://updated.example.com", "owner-token", Instant.now(), null, true);
        when(urlService.updateUrl(eq("abc123"), eq("owner-token"), any())).thenReturn(response);

        mockMvc.perform(put("/api/v1/urls/abc123")
                        .header("X-Owner-Token", "owner-token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"originalUrl\": \"https://updated.example.com\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.originalUrl").value("https://updated.example.com"));
    }

    @Test
    void updateReturns403WhenOwnerMismatch() throws Exception {
        when(urlService.updateUrl(eq("abc123"), any(), any()))
                .thenThrow(new UnauthorizedOwnerException("mismatch"));

        mockMvc.perform(put("/api/v1/urls/abc123")
                        .header("X-Owner-Token", "wrong-token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"originalUrl\": \"https://updated.example.com\"}"))
                .andExpect(status().isForbidden());
    }

    @Test
    void updateReturns404WhenNotFound() throws Exception {
        when(urlService.updateUrl(eq("missing"), any(), any()))
                .thenThrow(new UrlNotFoundException("not found"));

        mockMvc.perform(put("/api/v1/urls/missing")
                        .header("X-Owner-Token", "owner-token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"originalUrl\": \"https://updated.example.com\"}"))
                .andExpect(status().isNotFound());
    }

    @Test
    void deleteReturns204OnSuccess() throws Exception {
        mockMvc.perform(delete("/api/v1/urls/abc123").header("X-Owner-Token", "owner-token"))
                .andExpect(status().isNoContent());
    }

    @Test
    void deleteReturns403WhenOwnerMismatch() throws Exception {
        org.mockito.Mockito.doThrow(new UnauthorizedOwnerException("mismatch"))
                .when(urlService).deleteUrl(eq("abc123"), any());

        mockMvc.perform(delete("/api/v1/urls/abc123").header("X-Owner-Token", "wrong-token"))
                .andExpect(status().isForbidden());
    }

    @Test
    void deleteReturns404WhenNotFound() throws Exception {
        org.mockito.Mockito.doThrow(new UrlNotFoundException("not found"))
                .when(urlService).deleteUrl(eq("missing"), any());

        mockMvc.perform(delete("/api/v1/urls/missing").header("X-Owner-Token", "owner-token"))
                .andExpect(status().isNotFound());
    }
}
