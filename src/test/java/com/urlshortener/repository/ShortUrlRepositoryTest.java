package com.urlshortener.repository;

import com.urlshortener.entity.ShortUrlEntity;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.dao.DataIntegrityViolationException;

import java.time.Instant;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DataJpaTest
class ShortUrlRepositoryTest {

    @org.springframework.beans.factory.annotation.Autowired
    private ShortUrlRepository repository;

    private ShortUrlEntity newEntity(String shortCode, boolean active) {
        ShortUrlEntity entity = new ShortUrlEntity(shortCode, "https://example.com/" + shortCode,
                false, UUID.randomUUID(), Instant.now(), null);
        entity.setActive(active);
        return entity;
    }

    @Test
    void persistsAndFindsByShortCode() {
        repository.save(newEntity("abc123", true));

        assertThat(repository.findByShortCode("abc123"))
                .isPresent()
                .get()
                .satisfies(entity -> assertThat(entity.getOriginalUrl()).isEqualTo("https://example.com/abc123"));
    }

    @Test
    void findByShortCodeReturnsEmptyWhenAbsent() {
        assertThat(repository.findByShortCode("nope")).isEmpty();
    }

    @Test
    void enforcesUniqueConstraintOnShortCode() {
        repository.save(newEntity("dupCode", true));
        repository.flush();

        assertThatThrownBy(() -> {
            repository.save(newEntity("dupCode", true));
            repository.flush();
        }).isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void existsByShortCodeReflectsPersistedState() {
        repository.save(newEntity("existsMe", true));

        assertThat(repository.existsByShortCode("existsMe")).isTrue();
        assertThat(repository.existsByShortCode("doesNotExist")).isFalse();
    }

    @Test
    void countByActiveTrueCountsOnlyActiveRows() {
        repository.save(newEntity("active1", true));
        repository.save(newEntity("active2", true));
        repository.save(newEntity("inactive1", false));

        assertThat(repository.countByActiveTrue()).isEqualTo(2);
    }
}
