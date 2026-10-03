# UI-01 designer decisions

1. **Authorise form on both `/` and `/authorizations`** (one component): the spec lists its test ids with the wallet changes and with the new route, so both pages carry it.
2. **Unchanged resubmit after success sends nothing** ("must not send another payment"); a retry after an unknown outcome resends the same key and body.
3. **`wallet-*` ids only on `/`.** Other screens show a compact header balance (`.balance-chip`) without them.
4. **Typography is two system font stacks, no font files**: offline, no licence, no flash of fallback.
5. **No tabs or collapsed panels on `/`**: all three forms are visible so every input is fillable without a click first.
6. **`current-handle` text is exactly the handle**; the "@" is drawn by CSS `::before` and is not in `textContent`.
7. **Browser console 4xx lines.** Chromium logs every non-2xx fetch as "Failed to load resource". The UI shows refusals as designed (login-error, refused pay), so a tool that fails on any console error flags expected refusals; the checks in `stage-2/tools/ui_check.py` ignore only the "status of 4xx" resource lines.
