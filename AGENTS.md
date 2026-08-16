# Agent guidance

Signal K plugin that streams a browser-rendered dashboard to an ESP32-P4 panel
as MJPEG over TCP, with touch events coming back. See README.md for the
architecture table.

## Licensing

This project is **source-available, not open source**: use and modification are
free, redistribution is not. `LICENSE.md` is authoritative.

- **There is no permissive-era release to grandfather.** `package.json` carried
  `"license": "MIT"` as an unedited scaffold default with no LICENSE file
  behind it, and nothing was ever published to npm or tagged. So unlike the
  other plugins in this family there is no `LICENSE-MIT-through-vX` file —
  writing one would imply a public MIT release that never happened.
- **Never propose returning to a permissive license** — that is the copyright
  holder's decision alone.
- `package.json` uses `"license": "SEE LICENSE IN LICENSE.md"`. This is not an
  SPDX-listed license; inventing an identifier breaks tooling validation.
- `CONTRIBUTING.md` carries an inbound contribution grant.
- The license text derives from a plain-language template whose authors permit
  adaptation only if all mention of their project is removed. It has been. Do
  not add attribution to them back in.
- **Runtime dependency licenses gate this.** The only runtime dependency is
  `@signalk/server-api` (Apache-2.0); its transitive tree is ISC / MIT /
  Apache-2.0. Re-check before adding a runtime dependency — devDependencies do
  not matter, since they are never distributed.

## Packaging

`files` in package.json is an allowlist: `dist/`, LICENSE.md and README.md
ship. **This matters more than usual here** — the `*.py` helper scripts live at
the repo root, and without the allowlist `npm publish` would pack the entire
working tree, Python scripts included. Do not remove it.

The plugin has never been published or tagged. If that changes, it needs a
publish workflow, and the npm-version trap applies: OIDC trusted publishing
requires npm ≥ 11.5, while `npm@latest` (npm 12) breaks `--provenance` with
"Cannot find module 'sigstore'". Pin `npm@^11`.

## Architecture notes

- The plugin **spawns external processes** — Xvfb, Chromium, ffmpeg — and
  supervises them, restarting the chain after `RESTART_DELAY_MS` if any exits.
  None of them are bundled; they must be installed on the Signal K host.
- `start()` must never throw: a thrown plugin can take down signalk-server.
  Failure paths log via `app.error()` and return.
- The `*.py` files are bring-up aids (standalone test server, native status
  display, two touch-listener variants), not part of the plugin runtime.

## Conventions

- Angular conventional commits; branch names use hyphens, never slashes.
- Never commit directly to `master`; open a PR.
- No `Co-Authored-By` lines and no AI attribution anywhere.
- No test suite or CI exists yet. Don't claim tests ran when they didn't.
