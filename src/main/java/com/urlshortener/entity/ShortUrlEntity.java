package com.urlshortener.entity;

import jakarta.persistence.*;

import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "short_urls",
        uniqueConstraints = @UniqueConstraint(name = "uq_short_code", columnNames = "short_code"),
        indexes = {
                @Index(name = "idx_short_code_active", columnList = "short_code, active"),
                @Index(name = "idx_expires_at", columnList = "expires_at"),
                @Index(name = "idx_owner_token", columnList = "owner_token")
        })
public class ShortUrlEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "short_code", nullable = false, length = 16)
    private String shortCode;

    @Column(name = "original_url", nullable = false, length = 2048)
    private String originalUrl;

    @Column(name = "custom_alias", nullable = false)
    private boolean customAlias;

    @Column(name = "owner_token", nullable = false)
    private UUID ownerToken;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "expires_at")
    private Instant expiresAt;

    @Column(name = "active", nullable = false)
    private boolean active = true;

    @Column(name = "click_count", nullable = false)
    private long clickCount = 0;

    @Column(name = "first_accessed_at")
    private Instant firstAccessedAt;

    @Column(name = "last_accessed_at")
    private Instant lastAccessedAt;

    protected ShortUrlEntity() {
    }

    public ShortUrlEntity(String shortCode, String originalUrl, boolean customAlias,
                           UUID ownerToken, Instant createdAt, Instant expiresAt) {
        this.shortCode = shortCode;
        this.originalUrl = originalUrl;
        this.customAlias = customAlias;
        this.ownerToken = ownerToken;
        this.createdAt = createdAt;
        this.expiresAt = expiresAt;
    }

    public Long getId() {
        return id;
    }

    public String getShortCode() {
        return shortCode;
    }

    public void setShortCode(String shortCode) {
        this.shortCode = shortCode;
    }

    public String getOriginalUrl() {
        return originalUrl;
    }

    public void setOriginalUrl(String originalUrl) {
        this.originalUrl = originalUrl;
    }

    public boolean isCustomAlias() {
        return customAlias;
    }

    public UUID getOwnerToken() {
        return ownerToken;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getExpiresAt() {
        return expiresAt;
    }

    public void setExpiresAt(Instant expiresAt) {
        this.expiresAt = expiresAt;
    }

    public boolean isActive() {
        return active;
    }

    public void setActive(boolean active) {
        this.active = active;
    }

    public long getClickCount() {
        return clickCount;
    }

    public void setClickCount(long clickCount) {
        this.clickCount = clickCount;
    }

    public Instant getFirstAccessedAt() {
        return firstAccessedAt;
    }

    public void setFirstAccessedAt(Instant firstAccessedAt) {
        this.firstAccessedAt = firstAccessedAt;
    }

    public Instant getLastAccessedAt() {
        return lastAccessedAt;
    }

    public void setLastAccessedAt(Instant lastAccessedAt) {
        this.lastAccessedAt = lastAccessedAt;
    }
}
