---
name: icon-search
description: "Search SVG icons by keyword with licenses (Iconify, OpenIconLibrary, Flaticon). Use for: \"find an icon for X\", \"search icons\", \"license of this icon\", /icon-search."
allowed-tools:
  - Bash
---

# icon-search

Find SVG icons and their license across three sources. Start with Iconify — it's free,
needs no key, and covers 150+ icon sets. Fall back to the others only when the user
names them or Iconify comes up empty for something niche.

## 1. Iconify (default, no key needed)

api.iconify.design is a free public JSON API. It's also what opensvg.dev/icons runs on
under the hood (opensvg.dev is a UI over the same collections: `mdi`, `tabler`,
`akar-icons`, `boxicons`, `ri`, `solar`, etc) — its own search data loads client-side and
isn't in static HTML, so scrape Iconify's API instead of opensvg.dev directly.

**Search by keyword** — returns matching icon ids (`prefix:name`) plus license/author for
every collection in the results, in one call:

```bash
curl -s "https://api.iconify.design/search?query=<term>&limit=32"
```

**Download an SVG:**

```bash
curl -s "https://api.iconify.design/<prefix>/<name>.svg" -o icon.svg
# optional recolor/resize
curl -s "https://api.iconify.design/<prefix>/<name>.svg?color=%23ff0000&width=24&height=24"
```

**Multiple icons at once** (JSON payload with SVG bodies inline):

```bash
curl -s "https://api.iconify.design/<prefix>.json?icons=<name1>,<name2>"
```

**Other lookups:**

```bash
# Full metadata (name, author, license, total icons) for one or more collections
curl -s "https://api.iconify.design/collections?prefix=<prefix1>,<prefix2>"
# All icon names in one collection
curl -s "https://api.iconify.design/collection?prefix=<prefix>"
```

Visual browsing: https://icon-sets.iconify.design

## 2. OpenIconLibrary (openiconlibrary.com)

Search and license lookup work unauthenticated. Actual SVG download is gated behind a
"Download verification required" check that curl can't pass (no referer/cookie combo
gets past it — it needs a real browser session or a registered API key). Use this
source for search/license answers; for the file itself, give the user the icon page URL
to open and download themselves, or use the authenticated API path below if they've
registered a key.

**Search (public, no key):**

```bash
curl -s "https://openiconlibrary.com/api/search-suggest?q=<term>"
```

Returns `icons: [{title, name, slug, pack_slug, pack_name}]`. Build the icon page URL as
`https://openiconlibrary.com/icons/<slug>`.

**License for a specific icon** — fetch its page and pull the `"license":"..."` field
from the embedded page data (it's server-rendered, present in the raw HTML):

```bash
curl -s -A "Mozilla/5.0" "https://openiconlibrary.com/icons/<slug>" | grep -oE '"license":"[^"]*"'
```

**Authenticated API** (full search/detail/svg-export, requires the user's own key —
they get one by logging in at https://openiconlibrary.com/login then checking
https://openiconlibrary.com/developers for the key/token flow; never register an
account on the user's behalf):

```bash
curl -s -H "Authorization: Bearer $OIL_API_KEY" "https://openiconlibrary.com/api/v1/search?q=<term>"
curl -s -H "Authorization: Bearer $OIL_API_KEY" "https://openiconlibrary.com/api/v1/icons/<id>/svg"
```

## 3. Flaticon (api.flaticon.com — needs the user's own API key)

Flaticon's site blocks plain curl (Cloudflare), and its real API is behind an
authenticated token — there's no free unauthenticated search. This always needs the
user to have registered their own app at https://api.flaticon.com/v3/docs and hold an
`apikey`/`secret` pair; never sign up or register an app on their behalf.

If the user has `FLATICON_API_KEY` / `FLATICON_API_SECRET` set:

```bash
# 1. exchange key+secret for a bearer token (valid ~30 days, cache it)
TOKEN=$(curl -s -X POST "https://api.flaticon.com/v3/app/authentication" \
  -H "Content-Type: application/json" \
  -d "{\"apikey\":\"$FLATICON_API_KEY\"}" | grep -oE '"token":"[^"]*"' | cut -d'"' -f4)

# 2. search
curl -s "https://api.flaticon.com/v3/search/icons/priority?q=<term>&limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

If those env vars aren't set, tell the user what's needed instead of attempting the
call — there's no anonymous path in.

**License matters here more than the others**: Flaticon icons are free to use with
attribution (a link back to Flaticon/the author) unless the user has a paid Premium
subscription that waives it. Always state this when handing back a Flaticon result —
don't imply it's license-free like a CC0/MIT icon would be.

## Notes

- Iconify icon ids are `prefix:name` (e.g. `mdi:home`). OpenIconLibrary uses opaque
  `slug`s. Flaticon uses numeric icon ids.
- Never hand back an icon without stating its license — that's the point of the search,
  not an afterthought. Licenses differ per source and even per collection within
  Iconify (MIT, Apache-2.0, CC-BY-4.0, OFL-1.1, CC0, "free with attribution", etc).
- Default to Iconify unless the user explicitly names OpenIconLibrary or Flaticon, or
  is hunting for something Iconify doesn't have (Flaticon's catalog skews toward
  colorful/illustrative packs; OpenIconLibrary toward CC0 and community packs).
