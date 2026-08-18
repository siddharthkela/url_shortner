package com.urlshortener.service;

import com.urlshortener.entity.ShortUrlEntity;
import com.urlshortener.repository.ShortUrlRepository;
import com.urlshortener.util.Base62Encoder;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class UrlServiceTest {

    @Mock
    private ShortUrlRepository repository;

    private UrlService urlService;

    @BeforeEach
    void setUp() {
        urlService = new UrlService(repository);
    }

    private ShortUrlEntity entityWithId(long id) {
        ShortUrlEntity entity = new ShortUrlEntity("placeholder", "https://example.com", false,
                java.util.UUID.randomUUID(), java.time.Instant.now(), null);
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
    void createSavesEntityTwiceAndReturnsBase62ShortCode() {
        ShortUrlEntity saved = entityWithId(42L);
        when(repository.save(any(ShortUrlEntity.class))).thenReturn(saved);

        String shortCode = urlService.createShortUrl("https://example.com/page");

        assertThat(shortCode).isEqualTo(Base62Encoder.encode(42L));
        verify(repository, times(2)).save(any(ShortUrlEntity.class));
    }

    @Test
    void resolveReturnsOriginalUrlWhenFound() {
        ShortUrlEntity entity = entityWithId(1L);
        entity.setShortCode("abc");
        when(repository.findByShortCode("abc")).thenReturn(Optional.of(entity));

        Optional<String> result = urlService.resolve("abc");

        assertThat(result).contains("https://example.com");
    }

    @Test
    void resolveReturnsEmptyWhenNotFound() {
        when(repository.findByShortCode("missing")).thenReturn(Optional.empty());

        assertThat(urlService.resolve("missing")).isEmpty();
    }
}
