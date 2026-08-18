package com.urlshortener.exception;

public class TooManyActiveUrlsException extends RuntimeException {
    public TooManyActiveUrlsException(String message) {
        super(message);
    }
}
