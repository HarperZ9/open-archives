# open-archives

[![tests](https://github.com/HarperZ9/open-archives/actions/workflows/ci.yml/badge.svg)](https://github.com/HarperZ9/open-archives/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-AGPL--3.0--only-e6e1d6?style=flat-square&labelColor=1a1712)](LICENSE)

open-archives searches free archives and museum collections with one query, from archive.org and Wikimedia Commons to the Met and NASA, and downloads the items you pick. It also cuts clips, audio loops and tiling textures from what you download. Each item is tagged with its licence, so you can see what you may ship and what is for reference only.

```
git clone https://github.com/HarperZ9/open-archives
cd open-archives
python -m openarchives search "cotton mill" --media image --from 1837 --to 1955 --save mills.json
python -m openarchives gather --results mills.json --pick 1,3,4 --max-mb 60 --sheet
```

`search` prints a ranked table: score, source, media type, year, licence class, rights basis and title. `gather` downloads the picks and writes a receipt listing each file, and `--sheet` adds contact sheets.

Use it for period reference images, b-roll and period sound for films, public domain posters and broadcasts, and textures, sounds and fonts for game and design work.

Python 3.11 or later, standard library only. Media work uses an ffmpeg binary: the tool finds it in `OPEN_ARCHIVES_FFMPEG`, then in the `imageio_ffmpeg` package if installed, then on `PATH`. Run `python -m openarchives sources --probe` to see which sources answer from your machine.

## Commands

| Command | What it does |
|---|---|
| `search QUERY` | One query across every adapter. Filters: `--media`, `--from`, `--to`, `--strict-era`, `--licence`, `--sources`. |
| `gather` | Search or load saved results, download with caps, write a receipt. `--skip-reference` downloads shippable items only. |
| `sources [--probe]` | Lists adapters and their status. `--probe` runs a small live query against each. |
| `sheet KIND` | Contact sheets. `video` (a file or URL), `stream` (video results, streamed, nothing kept), `images`, `audio`, `receipt`, `results` (thumbnails). |
| `fetch URL` | Any web address. Honours robots.txt and records the rights basis. `--media N` also takes media linked from the page. |
| `derive OP IN OUT` | `clip`, `audio`, `loop`, `crop`, `texture`, `grade`, `pitch`. Each writes an asset receipt with lineage. |
| `register FILE --ref ...` | Records an asset made by hand and the library files that were in view while making it. |
| `check-derived ASSET` | The clean-room gate. Exit code 2 on a fail. |
| `rights KEY --basis B --reason R` | Records a basis by hand, such as fair use or a licence you hold. Dated, append-only. |
| `basis` | Lists which assets ship on which basis, and which are blocked. |
| `credits` | Writes `CREDITS.md` from the asset receipts. |

Media types: `image`, `video`, `audio`, `text`, `texture`, `font`, `model3d`, `dataset`. A texture query also accepts photographs.

## Sources

Status from the live probe on 2026-10-23. Each adapter follows the documentation linked in its module, checked the same day.

| Adapter | Covers | Status |
|---|---|---|
| `internet_archive` | everything on archive.org (advancedsearch, metadata, download) | working |
| `ia_prelinger` | Prelinger ephemeral films | working |
| `ia_78rpm` | Great 78 Project and the 78rpm collection | working; most 78s carry no licence statement |
| `ia_etree` | Live Music Archive | working; off by default, mostly non-commercial terms |
| `musopen` | Musopen recordings | working through the Internet Archive mirror; Musopen has no public search API |
| `wikimedia_commons` | images, audio, video, documents | working |
| `loc` | Library of Congress photos, film, audio, books | working; most items say "no known restrictions", which gates to reference only |
| `met` | Metropolitan Museum open access | working; uses the paginated v1.1 search, since v1 search was retired on 2026-10-01 |
| `rijksmuseum` | Rijksmuseum Linked Art search | working, keyless; capped at 6 objects a query because each needs three lookups |
| `artic` | Art Institute of Chicago | working; sends the `AIC-User-Agent` header the AIC docs ask for |
| `cleveland` | Cleveland Museum of Art open access | working |
| `wellcome` | Wellcome Collection images | working |
| `nasa` | NASA Image and Video Library | working |
| `openverse` | CC images and audio, including Flickr and Freesound | working; audio comes as the provider's preview file |
| `gutenberg` | Project Gutenberg through Gutendex | working |
| `zenodo` | datasets and corpora | working |
| `polyhaven` | CC0 textures, HDRIs and 3D models | working |
| `fontsource` | open-licensed fonts | working |
| `smithsonian` | Smithsonian Open Access | needs a key in `SI_API_KEY` (api.data.gov) |
| `nypl` | NYPL Digital Collections | needs a token in `NYPL_API_TOKEN` |
| `europeana` | Europeana | needs a key in `EUROPEANA_API_KEY` |
| `freesound` | Freesound | needs a key in `FREESOUND_API_KEY`; CC sounds are reachable keyless through Openverse |
| `bhl` | Biodiversity Heritage Library | needs a key in `BHL_API_KEY` |
| `sciencemuseum` | Science Museum Group | blocked: its CDN returns 403 to scripted clients; off by default and not worked around |

Keyed adapters stay skipped until you set the variable. `.env.example` lists every one. Keys are read from the environment and never written to receipts.

## Rights handling

Each item keeps the source's own rights words verbatim, a normalised licence class and a rights basis.

Licence classes: `pd`, `cc0`, `cc-by`, `cc-by-sa`, `nc`, `nd`, `ofl`, `permissive`, `nkr` (no known restrictions), `other-open`, `in-copyright`, `unknown`.

| Basis | Meaning |
|---|---|
| `free` | Public domain or CC0. Ships freely; credit is kept as a courtesy. |
| `own-work` | Made by you. Ships once the clean-room gate passes. |
| `credit` | CC BY, OFL or a permissive licence. Ships with the credit line. |
| `share-alike` | CC BY-SA. Ships with credit under the same licence. |
| `licensed` | You hold a licence. Set by hand with a written reason. |
| `fair-use` | Commentary or critique in an explainer. Set by hand with a written reason and the intended use. |
| `reference-only` | Everything else: NC, ND, no known restrictions, unknown, in copyright. Study only. |

Items marked "no known restrictions" stay reference only until you check them and record a basis with `rights`. Licence words found on a web page by `fetch` are kept as hints and do not clear an item, since a page footer usually covers the page text and not its media.

A derived asset takes the most restrictive basis among its inputs.

## Receipts

A gather receipt sits in `<library>/receipts/run-<time>-<tag>.json`. It holds the tool version, the User-Agent, the query, the caps, a licence and basis breakdown, and for every item: source, landing page, licence, rights words, attribution, status, and each file's path, URL, byte count and SHA-256. Every downloaded item is also appended to `<library>/index.jsonl`.

An asset receipt sits in `<library>/assets/<id>.json`, where the id is the first 16 hex digits of the file's SHA-256. It holds the operation and its parameters, the ffmpeg version, each input with its own SHA-256, item key, licence and basis, any references that were in view, the resulting basis, and the clean-room verdict.

## The library and its guards

Downloads go to `--library` if given, then `OPEN_ARCHIVES_LIBRARY`, then the first usable root in `OPEN_ARCHIVES_ROOTS` (a path list), then `~/archive-library`. On Windows, `OPEN_ARCHIVES_FORBIDDEN_DRIVES` (for example `D,F`) names drive letters the tool refuses to write to. Before a run the tool checks that free space covers the run cap plus 2 GB. Each run has a total cap (`--max-mb`, default 300) and a per-file cap (`--per-file-mb`, default 150). A file that declares a size over the cap is skipped, and a stream that grows past it is cut and its partial file removed.

Requests wait a minimum interval per host (one second by default, three for loc.gov), back off on 429 and 5xx responses, and name the tool with a contact URL in the User-Agent.

## Edit and repurpose

```
python -m openarchives derive texture IN.jpg OUT.png --size 1024 --mode plain
python -m openarchives derive texture IN.jpg OUT.png --size 512 --mode mirror --region 560,230,260,260
python -m openarchives derive loop IN.ogg OUT.wav --start 2 --length 8 --fade 1.0
python -m openarchives derive clip IN.mp4 OUT.mp4 --start 95 --length 12 --width 1280
```

`texture --mode plain` crops a square and scales it, for sources that already tile. `--mode mirror` mirrors a square crop into a 2x2 block, which tiles by construction but shows its symmetry on plain surfaces. Both write a 3x3 repeat preview to check seams. `loop` makes an audio loop with no gap or dip at the join: the audio after the loop end is faded out over the faded-in head, and the level is set with one static gain so the seam stays level. `audio` is a plain cut with fades.

## The clean-room gate

An asset made with reference-only material in view must not reproduce that material. `check-derived` compares the asset with every reference-only source in its lineage, following earlier derived assets back to their sources. Edits of public domain and CC0 sources need no gate, and neither do CC BY or CC BY-SA sources, whose licences already allow derivatives with credit.

Images are compared with a perceptual hash (DCT of a rank-equalised 32x32 window) plus a gradient hash. The derived image, its four quadrants, its centre and its flips are matched against thousands of source crops at many scales and positions, and the best candidates are refined by hill-climbing. Rank equalisation makes the hash ignore brightness, contrast and most recolouring. Sound is compared with a spectral-shape fingerprint on semitone bands, searched across time offsets and pitch shifts of up to four semitones. Video is checked frame by frame. The asset fails when its best match reaches the threshold: 0.85 for images, 0.66 for sound.

Controls, 2026-10-23:

| Control | Similarity | Verdict |
|---|---|---|
| Synthetic texture, recoloured / cropped / cropped and flipped / mirror-tiled | 0.99 / 0.97 / 0.95 / 0.96 | fail |
| Independent synthetic textures of the same kind | 0.70 to 0.75 | pass |
| LoC flood photograph, recoloured, cropped and mirrored | 0.99 | fail |
| Two independent flood photographs from other sources | 0.76, 0.77 | pass |
| Synthetic melody, excerpted / pitched up 2 / pitched down 1 | 0.99 / 0.76 / 0.79 | fail |
| Pitched ambience excerpt | 0.82 | fail |
| Independent melodies in the same timbre, independent ambience | 0.51 to 0.53 | pass |
| 1926 78rpm side, pitched up a semitone with EQ | 0.87 | fail |
| Another side by the same orchestra from the same session; a side by a different band | 0.56, 0.55 | pass |

The gate checks for reproduction of a specific source. It does not catch looser copying, such as a character redrawn from memory, and a pass is not legal clearance. Independent real photographs scored up to 0.77 against the 0.85 image threshold, so two closely similar photographs can land near it.

## Tests

```
python -m unittest discover -s tests -t .
```

35 tests, under a minute. The licence, adapter, search and library tests take about two seconds. They run against API responses captured live on 2026-10-23 and a local HTTP server, so they need no network. The clean-room tests build their own controls with ffmpeg; `pip install imageio-ffmpeg` is the quickest way to get one. CI runs the suite on Linux and Windows for every push and pull request.

## Layout

```
openarchives/
  net.py            HTTP client: User-Agent, pacing, retries, caps, SHA-256
  licence.py        licence classes, rights bases, attribution
  model.py          the Item record shared by every adapter
  search.py         fan-out, filters, de-duplication, ranking
  library.py        library root, guards, gather, receipts
  sheets.py         contact sheets
  derive.py         clip, audio, loop, crop, texture, grade, pitch
  rights.py         asset receipts, overrides, basis report, credits
  cleanroom.py      the clean-room gate
  perceptual.py     image hashes and crop search
  audioprint.py     audio fingerprint
  webfetch.py       any-URL fetch with robots.txt
  mediatools.py     ffmpeg wrapper
  adapters/         one module per family of sources
tests/              unit tests and captured API responses
```

## License

The code is licensed under the GNU Affero General Public License, version 3 only (AGPL-3.0-only). You may use, study, change and share it. If you run a changed version as a network service, you must offer its users the source of that version. See [LICENSE](LICENSE). Copyright (C) 2026 Zain Dana Harper.

The licence covers this tool and nothing it finds. Each downloaded item keeps the terms its source gives it, and the receipts record them.
