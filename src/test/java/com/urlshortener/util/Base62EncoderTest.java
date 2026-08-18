package com.urlshortener.util;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.util.HashSet;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class Base62EncoderTest {

    @Test
    void encodesZeroAsFirstAlphabetCharacter() {
        assertThat(Base62Encoder.encode(0)).isEqualTo("0");
    }

    @Test
    void encodesKnownValues() {
        assertThat(Base62Encoder.encode(1)).isEqualTo("1");
        assertThat(Base62Encoder.encode(61)).isEqualTo("z");
        assertThat(Base62Encoder.encode(62)).isEqualTo("10");
    }

    @ParameterizedTest
    @ValueSource(longs = {0, 1, 61, 62, 12345, 999999999L, Long.MAX_VALUE})
    void roundTripsEncodeAndDecode(long value) {
        String encoded = Base62Encoder.encode(value);
        assertThat(Base62Encoder.decode(encoded)).isEqualTo(value);
    }

    @Test
    void rejectsNegativeValues() {
        assertThatThrownBy(() -> Base62Encoder.encode(-1))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsInvalidCharacterOnDecode() {
        assertThatThrownBy(() -> Base62Encoder.decode("!!!"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsNullOrEmptyOnDecode() {
        assertThatThrownBy(() -> Base62Encoder.decode(null)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> Base62Encoder.decode("")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void sequentialIdsProduceCollisionFreeCodes() {
        Set<String> codes = new HashSet<>();
        for (long i = 0; i < 10_000; i++) {
            assertThat(codes.add(Base62Encoder.encode(i))).isTrue();
        }
    }
}
