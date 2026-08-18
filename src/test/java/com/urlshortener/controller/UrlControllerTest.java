package com.urlshortener.controller;

import com.urlshortener.dto.UrlResponse;
import com.urlshortener.exception.AliasAlreadyExistsException;
import com.urlshortener.exception.TooManyActiveUrlsException;
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
        when(urlService.createShortUrl(any())).thenReturn(response);

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
        when(urlService.createShortUrl(any())).thenThrow(new AliasAlreadyExistsException("taken"));

        mockMvc.perform(post("/api/v1/urls")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"originalUrl\": \"https://example.com\", \"customAlias\": \"taken123\"}"))
                .andExpect(status().isConflict());
    }

    @Test
    void createReturns429WhenCapReached() throws Exception {
        when(urlService.createShortUrl(any())).thenThrow(new TooManyActiveUrlsException("cap reached"));

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
}
