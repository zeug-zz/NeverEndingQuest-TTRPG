# toolkit-provider-lazy-log-safety

Ensure provider transport logging remains redacted and non-verbose when OpenAI, httpx, and httpcore child loggers are created lazily after shared factory initialization.
