package com.urlshortener.repository;

import com.urlshortener.entity.ShortUrlEntity;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.Optional;

public interface ShortUrlRepository extends JpaRepository<ShortUrlEntity, Long> {

    Optional<ShortUrlEntity> findByShortCode(String shortCode);

    boolean existsByShortCode(String shortCode);

    long countByActiveTrue();

    /**
     * Single atomic bulk UPDATE — the DB engine computes clickCount + 1 against the
     * row's current value under its own lock. Never read clickCount into Java and
     * write it back; that reintroduces a lost-update race under concurrent redirects.
     */
    @Modifying(clearAutomatically = true)
    @Query("UPDATE ShortUrlEntity s SET s.clickCount = s.clickCount + 1, " +
            "s.firstAccessedAt = COALESCE(s.firstAccessedAt, :now), s.lastAccessedAt = :now " +
            "WHERE s.shortCode = :shortCode")
    int incrementClickCount(@Param("shortCode") String shortCode, @Param("now") Instant now);
}
