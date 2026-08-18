package com.urlshortener.exception;

public class UnauthorizedOwnerException extends RuntimeException {
    public UnauthorizedOwnerException(String message) {
        super(message);
    }
}
