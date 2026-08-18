package com.urlshortener.service;

import com.urlshortener.entity.ShortUrlEntity;
import com.urlshortener.repository.ShortUrlRepository;
import com.urlshortener.util.Base62Encoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

@Service
public class UrlService {

    private final ShortUrlRepository repository;

    public UrlService(ShortUrlRepository repository) {
        this.repository = repository;
    }

    /**
     * The short code is derived from the DB-assigned ID (Base62), so the entity is
     * saved once with a placeholder short_code to obtain the generated ID, then
     * updated with the real code. Both writes happen in the same transaction.
     */
    @Transactional
    public String createShortUrl(String originalUrl) {
        UUID ownerToken = UUID.randomUUID();
        String placeholder = UUID.randomUUID().toString().substring(0, 16);
        ShortUrlEntity entity = new ShortUrlEntity(placeholder, originalUrl, false, ownerToken, Instant.now(), null);
        entity = repository.save(entity);
        entity.setShortCode(Base62Encoder.encode(entity.getId()));
        repository.save(entity);
        return entity.getShortCode();
    }

    public Optional<String> resolve(String shortCode) {
        return repository.findByShortCode(shortCode).map(ShortUrlEntity::getOriginalUrl);
    }
}
