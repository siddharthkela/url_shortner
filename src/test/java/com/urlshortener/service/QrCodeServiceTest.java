package com.urlshortener.service;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class QrCodeServiceTest {

    private final QrCodeService qrCodeService = new QrCodeService();

    @Test
    void generatesNonEmptyPngBytes() {
        byte[] png = qrCodeService.generatePng("http://localhost:8080/abc123");

        assertThat(png).isNotEmpty();
        // PNG magic number: 0x89 'P' 'N' 'G' 0x0D 0x0A 0x1A 0x0A
        assertThat(png[0]).isEqualTo((byte) 0x89);
        assertThat(png[1]).isEqualTo((byte) 'P');
        assertThat(png[2]).isEqualTo((byte) 'N');
        assertThat(png[3]).isEqualTo((byte) 'G');
    }

    @Test
    void differentContentProducesDifferentImages() {
        byte[] first = qrCodeService.generatePng("http://localhost:8080/aaa111");
        byte[] second = qrCodeService.generatePng("http://localhost:8080/zzz999");

        assertThat(first).isNotEqualTo(second);
    }

    @Test
    void handlesLongUrlsWithinQrCapacity() {
        String longUrl = "http://localhost:8080/" + "a".repeat(100);
        byte[] png = qrCodeService.generatePng(longUrl);

        assertThat(png).isNotEmpty();
    }
}
