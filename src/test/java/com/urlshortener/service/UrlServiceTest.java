package com.urlshortener.service;

import com.urlshortener.dto.CreateUrlRequest;
import com.urlshortener.dto.UpdateUrlRequest;
import com.urlshortener.dto.UrlResponse;
import com.urlshortener.entity.ShortUrlEntity;
import com.urlshortener.exception.AliasAlreadyExistsException;
import com.urlshortener.exception.InvalidUrlException;
import com.urlshortener.exception.TooManyActiveUrlsException;
import com.urlshortener.exception.UnauthorizedOwnerException;
import com.urlshortener.exception.UrlExpiredException;
import com.urlshortener.exception.UrlNotFoundException;
import com.urlshortener.repository.ShortUrlRepository;
import com.urlshortener.util.Base62Encoder;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class UrlServiceTest {

    @Mock
    private ShortUrlRepository repository;

    private UrlService urlService;

    @BeforeEach
    void setUp() {
        urlService = new UrlService(repository, 1000L, "http://localhost:8080");
    }

    private ShortUrlEntity entityWithId(long id, String shortCode, boolean customAlias) {
        return entityWithId(id, shortCode, customAlias, UUID.randomUUID(), null);
    }

    private ShortUrlEntity entityWithId(long id, String shortCode, boolean customAlias, UUID ownerToken, Instant expiresAt) {
        ShortUrlEntity entity = new ShortUrlEntity(shortCode, "https://example.com", customAlias,
                ownerToken, Instant.now(), expiresAt);
        setId(entity, id);
        return entity;
    }

    private void setId(ShortUrlEntity entity, long id) {
        try {
            var field = ShortUrlEntity.class.getDeclaredField("id");
            field.setAccessible(true);
            field.set(entity, id);
        } catch (ReflectiveOperationException e) {
            throw new RuntimeException(e);
        }
    }

    @Test
    void createsShortUrlWithGeneratedBase62Code() {
        when(repository.countByActiveTrue()).thenReturn(0L);
        ShortUrlEntity saved = entityWithId(42L, "placeholder", false);
        when(repository.save(any(ShortUrlEntity.class))).thenReturn(saved);

        UrlResponse response = urlService.createShortUrl(new CreateUrlRequest("https://example.com/page", null, null));

        assertThat(response.shortCode()).isEqualTo(Base62Encoder.encode(42L));
        assertThat(response.shortUrl()).isEqualTo("http://localhost:8080/" + Base62Encoder.encode(42L));
        verify(repository, times(2)).save(any(ShortUrlEntity.class));
    }

    @Test
    void retryWithSameIdempotencyKeyReturnsCachedResponseWithoutCreatingDuplicateRow() {
        when(repository.countByActiveTrue()).thenReturn(0L);
        ShortUrlEntity saved = entityWithId(42L, "placeholder", false);
        when(repository.save(any(ShortUrlEntity.class))).thenReturn(saved);

        CreateUrlRequest request = new CreateUrlRequest("https://example.com/page", null, null);
        UrlResponse first = urlService.createShortUrl(request, "idem-key-1");
        UrlResponse second = urlService.createShortUrl(request, "idem-key-1");

        assertThat(second).isEqualTo(first);
        verify(repository, times(2)).save(any(ShortUrlEntity.class));
    }

    @Test
    void differentIdempotencyKeysCreateDistinctRows() {
        when(repository.countByActiveTrue()).thenReturn(0L);
        when(repository.save(any(ShortUrlEntity.class)))
                .thenReturn(entityWithId(1L, "placeholder", false))
                .thenReturn(entityWithId(1L, "a", false))
                .thenReturn(entityWithId(2L, "placeholder", false))
                .thenReturn(entityWithId(2L, "b", false));

        CreateUrlRequest request = new CreateUrlRequest("https://example.com/page", null, null);
        UrlResponse first = urlService.createShortUrl(request, "idem-key-1");
        UrlResponse second = urlService.createShortUrl(request, "idem-key-2");

        assertThat(first.shortCode()).isNotEqualTo(second.shortCode());
        verify(repository, times(4)).save(any(ShortUrlEntity.class));
    }

    @Test
    void usesCustomAliasWhenProvidedAndAvailable() {
        when(repository.countByActiveTrue()).thenReturn(0L);
        when(repository.existsByShortCode("myalias")).thenReturn(false);
        ShortUrlEntity saved = entityWithId(1L, "myalias", true);
        when(repository.save(any(ShortUrlEntity.class))).thenReturn(saved);

        UrlResponse response = urlService.createShortUrl(new CreateUrlRequest("https://example.com/page", "myalias", null));

        assertThat(response.shortCode()).isEqualTo("myalias");
        verify(repository, times(1)).save(any(ShortUrlEntity.class));
    }

    @Test
    void throwsAliasAlreadyExistsWhenAliasTaken() {
        when(repository.countByActiveTrue()).thenReturn(0L);
        when(repository.existsByShortCode("taken")).thenReturn(true);

        assertThatThrownBy(() -> urlService.createShortUrl(new CreateUrlRequest("https://example.com", "taken", null)))
                .isInstanceOf(AliasAlreadyExistsException.class);
    }

    @Test
    void throwsInvalidUrlWhenSchemeIsNotHttpOrHttps() {
        assertThatThrownBy(() -> urlService.createShortUrl(new CreateUrlRequest("ftp://example.com/file", null, null)))
                .isInstanceOf(InvalidUrlException.class);
    }

    @Test
    void throwsInvalidUrlWhenMalformed() {
        assertThatThrownBy(() -> urlService.createShortUrl(new CreateUrlRequest("not a url", null, null)))
                .isInstanceOf(InvalidUrlException.class);
    }

    @Test
    void throwsInvalidUrlWhenExpiresAtIsInThePast() {
        Instant past = Instant.now().minus(1, ChronoUnit.DAYS);
        assertThatThrownBy(() -> urlService.createShortUrl(new CreateUrlRequest("https://example.com", null, past)))
                .isInstanceOf(InvalidUrlException.class);
    }

    @Test
    void throwsTooManyActiveUrlsWhenCapReached() {
        urlService = new UrlService(repository, 1L, "http://localhost:8080");
        when(repository.countByActiveTrue()).thenReturn(1L);

        assertThatThrownBy(() -> urlService.createShortUrl(new CreateUrlRequest("https://example.com", null, null)))
                .isInstanceOf(TooManyActiveUrlsException.class);
    }

    @Test
    void resolveReturnsOriginalUrlWhenActiveAndFound() {
        ShortUrlEntity entity = entityWithId(1L, "abc", false);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        assertThat(urlService.resolve("abc")).isEqualTo("https://example.com");
    }

    @Test
    void resolveIncrementsClickCountViaAtomicUpdateNotReadModifyWrite() {
        ShortUrlEntity entity = entityWithId(1L, "abc", false);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        urlService.resolve("abc");

        verify(repository, times(1)).incrementClickCount(eq("abc"), any(Instant.class));
        verify(repository, never()).save(any(ShortUrlEntity.class));
    }

    @Test
    void resolveThrowsUrlNotFoundWhenMissing() {
        when(repository.findByShortCode("missing")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> urlService.resolve("missing")).isInstanceOf(UrlNotFoundException.class);
    }

    @Test
    void resolveThrowsUrlNotFoundWhenInactive() {
        ShortUrlEntity entity = entityWithId(1L, "abc", false);
        entity.setActive(false);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        assertThatThrownBy(() -> urlService.resolve("abc")).isInstanceOf(UrlNotFoundException.class);
    }

    @Test
    void getDetailsReturnsResponseWhenFound() {
        ShortUrlEntity entity = entityWithId(1L, "abc", false);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        UrlResponse response = urlService.getDetails("abc");

        assertThat(response.shortCode()).isEqualTo("abc");
        assertThat(response.originalUrl()).isEqualTo("https://example.com");
    }

    @Test
    void getDetailsThrowsUrlNotFoundWhenMissing() {
        when(repository.findByShortCode("missing")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> urlService.getDetails("missing")).isInstanceOf(UrlNotFoundException.class);
    }

    @Test
    void getAnalyticsReturnsClickCountAndTimestamps() {
        ShortUrlEntity entity = entityWithId(1L, "abc", false);
        entity.setClickCount(7);
        Instant first = Instant.now().minusSeconds(60);
        Instant last = Instant.now();
        entity.setFirstAccessedAt(first);
        entity.setLastAccessedAt(last);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        var response = urlService.getAnalytics("abc");

        assertThat(response.shortCode()).isEqualTo("abc");
        assertThat(response.clickCount()).isEqualTo(7);
        assertThat(response.firstAccessedAt()).isEqualTo(first);
        assertThat(response.lastAccessedAt()).isEqualTo(last);
    }

    @Test
    void getAnalyticsThrowsUrlNotFoundWhenMissing() {
        when(repository.findByShortCode("missing")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> urlService.getAnalytics("missing")).isInstanceOf(UrlNotFoundException.class);
    }

    @Test
    void resolveThrowsUrlExpiredWhenPastExpiry() {
        Instant past = Instant.now().minusSeconds(60);
        ShortUrlEntity entity = entityWithId(1L, "abc", false, UUID.randomUUID(), past);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        assertThatThrownBy(() -> urlService.resolve("abc")).isInstanceOf(UrlExpiredException.class);
    }

    @Test
    void getDetailsThrowsUrlExpiredWhenPastExpiry() {
        Instant past = Instant.now().minusSeconds(60);
        ShortUrlEntity entity = entityWithId(1L, "abc", false, UUID.randomUUID(), past);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        assertThatThrownBy(() -> urlService.getDetails("abc")).isInstanceOf(UrlExpiredException.class);
    }

    @Test
    void updateUrlChangesOriginalUrlAndExpiresAtWhenOwnerMatches() {
        UUID ownerToken = UUID.randomUUID();
        ShortUrlEntity entity = entityWithId(1L, "abc", false, ownerToken, null);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));
        when(repository.save(any(ShortUrlEntity.class))).thenAnswer(inv -> inv.getArgument(0));

        Instant newExpiry = Instant.now().plusSeconds(3600);
        UrlResponse response = urlService.updateUrl("abc", ownerToken.toString(),
                new UpdateUrlRequest("https://updated.example.com", newExpiry));

        assertThat(response.originalUrl()).isEqualTo("https://updated.example.com");
        assertThat(response.expiresAt()).isEqualTo(newExpiry);
    }

    @Test
    void updateUrlAllowsExtendingAnAlreadyExpiredUrl() {
        UUID ownerToken = UUID.randomUUID();
        Instant past = Instant.now().minusSeconds(60);
        ShortUrlEntity entity = entityWithId(1L, "abc", false, ownerToken, past);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));
        when(repository.save(any(ShortUrlEntity.class))).thenAnswer(inv -> inv.getArgument(0));

        Instant newExpiry = Instant.now().plusSeconds(3600);
        UrlResponse response = urlService.updateUrl("abc", ownerToken.toString(),
                new UpdateUrlRequest(null, newExpiry));

        assertThat(response.expiresAt()).isEqualTo(newExpiry);
    }

    @Test
    void updateUrlThrowsUnauthorizedOwnerWhenTokenMismatch() {
        ShortUrlEntity entity = entityWithId(1L, "abc", false, UUID.randomUUID(), null);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        assertThatThrownBy(() -> urlService.updateUrl("abc", UUID.randomUUID().toString(),
                new UpdateUrlRequest("https://other.example.com", null)))
                .isInstanceOf(UnauthorizedOwnerException.class);
    }

    @Test
    void updateUrlThrowsUnauthorizedOwnerWhenTokenMissing() {
        ShortUrlEntity entity = entityWithId(1L, "abc", false, UUID.randomUUID(), null);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        assertThatThrownBy(() -> urlService.updateUrl("abc", null,
                new UpdateUrlRequest("https://other.example.com", null)))
                .isInstanceOf(UnauthorizedOwnerException.class);
    }

    @Test
    void updateUrlThrowsUrlNotFoundWhenMissing() {
        when(repository.findByShortCode("missing")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> urlService.updateUrl("missing", UUID.randomUUID().toString(),
                new UpdateUrlRequest("https://example.com", null)))
                .isInstanceOf(UrlNotFoundException.class);
    }

    @Test
    void deleteUrlSetsInactiveWhenOwnerMatches() {
        UUID ownerToken = UUID.randomUUID();
        ShortUrlEntity entity = entityWithId(1L, "abc", false, ownerToken, null);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));
        when(repository.save(any(ShortUrlEntity.class))).thenAnswer(inv -> inv.getArgument(0));

        urlService.deleteUrl("abc", ownerToken.toString());

        assertThat(entity.isActive()).isFalse();
        verify(repository).save(entity);
    }

    @Test
    void deleteUrlThrowsUnauthorizedOwnerWhenTokenMismatch() {
        ShortUrlEntity entity = entityWithId(1L, "abc", false, UUID.randomUUID(), null);
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        assertThatThrownBy(() -> urlService.deleteUrl("abc", UUID.randomUUID().toString()))
                .isInstanceOf(UnauthorizedOwnerException.class);
        assertThat(entity.isActive()).isTrue();
    }

    @Test
    void deleteUrlThrowsUrlNotFoundWhenMissing() {
        when(repository.findByShortCode("missing")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> urlService.deleteUrl("missing", UUID.randomUUID().toString()))
                .isInstanceOf(UrlNotFoundException.class);
    }
}
