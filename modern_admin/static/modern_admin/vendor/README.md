# Vendored browser dependencies

- Alpine: `@alpinejs/csp@3.17.1`, MIT, `dist/cdn.min.js` from the official npm tarball.
  Integrity: `sha512-HDrY0ZxvJWSmeUYqtHVSsitaqy1es3VDCNodPpdQRX4nHhHiRoeib+rOzRFFStFRD/6x0KmQzJVJ4FCLAI/DUQ==`.
  Source: https://github.com/alpinejs/alpine/tree/v3.17.1/packages/csp
- HTMX: 2.0.7 (existing distribution).

Use the CSP package when updating Alpine. Do not replace it with the default evaluator.
