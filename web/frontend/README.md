# Player frontend build

Run `npm run build` from this directory (or `npm --prefix web/frontend run build`) to produce the ignored `dist/` player shell, flat content-hashed assets, and `player-manifest.json`. The Vite base path is `/static/player/`; the shell is served separately at `/` by the player listener. No host name or development URL is configured in the client build.

## Player manifest

The manifest is deterministic ASCII JSON with sorted asset IDs and a trailing newline:

```json
{
  "manifest_version": 1,
  "protocol_version": 1,
  "client_build_id": "<32 lowercase hex characters>",
  "shell": {
    "file": "index.html",
    "sha256": "<64 lowercase hex characters>",
    "bytes": 0,
    "content_type": "text/html; charset=utf-8"
  },
  "assets": {
    "<asset-id>": {
      "file": "<same flat asset-id>",
      "sha256": "<64 lowercase hex characters>",
      "bytes": 0,
      "content_type": "<fixed MIME type>"
    }
  }
}
```

Asset IDs are ASCII `[A-Za-z0-9._-]{1,128}` flat filenames. The fixed MIME map is `.js` (`text/javascript; charset=utf-8`), `.css` (`text/css; charset=utf-8`), `.svg` (`image/svg+xml`), `.png` (`image/png`), and `.woff2` (`font/woff2`); other extensions fail the build. At most 64 assets and 8 MiB aggregate asset bytes are accepted. Every filename is content-hashed and every digest is full SHA-256.

`client_build_id` is the first 32 hex characters of SHA-256 over the sorted rows `asset-id<TAB>asset-sha256<LF>`. It intentionally excludes the shell digest because the build ID is injected into the shell as a meta value; the shell's full SHA-256 and byte length are computed after injection. The shell also carries the fixed protocol version in non-script meta data. Vite source maps and its module-preload polyfill are disabled, and inline scripts are rejected.

Run `npm run test:manifest` for built-in Node validation tests. `npm test -- --run` runs the Vitest suite.
