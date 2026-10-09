# App artwork

## TODO before public release

These three files are copies of `apps/web/public/brand/infinity-mark.png`,
which is **512×512** — the largest square InfinityPay mark in the repo.
That is enough to build and ship to an internal testing track, and it is
exactly the size the Play Store **listing icon** requires, but it is below
what the build wants as a source asset.

Replace with real 1024×1024 artwork before any public release:

| File | Needed | Have | Used for |
|---|---|---|---|
| `icon.png` | 1024×1024, no transparency | 512×512 RGBA | iOS app icon, Android fallback |
| `adaptive-icon.png` | 1024×1024, subject inside the centre 66% | 512×512 RGBA | Android adaptive icon foreground |
| `splash.png` | 1024×1024 (or wider artwork) | 512×512 RGBA | Launch screen, on `#04332a` |

Deliberately **not** done here: upscaling the 512×512 mark to 1024×1024.
That produces a soft icon that looks like a mistake on a modern phone, and
it would hide the fact that the real artwork is still missing.

## Play Store listing assets

These are uploaded in the Play Console, not built into the app, and are
not in this folder:

- Listing icon — 512×512 PNG. `apps/web/public/brand/infinity-mark.png` is
  already the right size.
- Feature graphic — 1024×500 PNG/JPG. None exists yet.
  `apps/web/public/og/infinitypay-og-v2.png` (1200×630) is the closest
  thing, but it is an Open Graph image, not a crop-safe feature graphic —
  treat it as a starting point for a designer, not a drop-in.
- Screenshots — at least two phone screenshots, taken from a real build.

See `../PLAY_STORE_INTERNAL_TESTING.md`.
