# Golfausflug Funnel - Autonomous Email Engine

Demo AI system for **goHartl golftours** (golfausflug.de) - German golf trips to
South Africa. A lead fills the Google Form, and this engine sends them a fully
personalized German trip plan, then runs an on-thread email conversation that
refines the plan up to 15 rounds before handing off to Gerd Schoenberg.

This project is **completely separate from the SmarterFlow estimate funnel**. It
never reads, imports, or touches anything under `scripts/hl-funnel/` or
`hl-estimate-watcher/`, and it never mentions SmarterFlow in any lead-facing
email (From line, body, signature are all goHartl / golfausflug.de).

## Moving parts

```
Google Form  ->  Forms API (gws)  ->  golfausflug-loop.py  ->  Gmail (gws)
1dxA3uqR...        poll responses      generate + send          send + reply
                                       via claude -p            + label thread
```

- **Form:** `1dxA3uqRyML4LUSr3494HbKv6vDjHLgdUBj0Cid4lVkU` (no spreadsheet needed - read directly via the Forms API).
- **Brain / source of truth:** `trip-knowledge.md` (read at runtime every run). All courses, hotels, regions, routing, and price logic come from this file only.
- **Generator:** `claude -p --model claude-opus-4-8` writes strict-JSON German emails (Sie-form, warm, "authentisch, familiaer und mit ganz viel Herz").
- **Sender:** `gws gmail users messages send` with hand-built RFC822 multipart/alternative (text + html), From "Golfausflug Suedafrika-Reiseplaner". Each thread is tagged with the Gmail label **Golfausflug-Funnel** (auto-created once).
- **State:** `state.json` - processed responseIds + per-lead record (threadId, rounds, lastMessageId, status). `runs.log` - one line per run.

## Lead handling

- **Complete rows** get a full day-by-day plan email (new thread).
- **PARTIAL rows** (Anmerkungen contains `PARTIAL`) are held 15 minutes: if a complete row from the same email arrives, only the complete one is used; after 15 min with no complete row, the partial is treated as an abandoned lead and gets a shorter invitation email.
- **Repeat submissions** from an email that was already served become a refreshed-plan REPLY on the existing thread (no new thread).
- **PIPELINE-TEST rows** (Anmerkungen contains `PIPELINE-TEST`) are skipped.
- **Reply rounds:** when a lead replies on the thread, the engine generates a focused refinement reply (up to 15 rounds), then hands off to Gerd.

## Personalized trip pages

Every **new complete lead** (not refinements, not abandoned/partial invites, not
follow-ups) also gets their own personalized trip **web page**, linked near the
top of their first plan email.

- **Template:** `trip-page-template.html` (Fable-designed). Its header comment
  documents every `{{PLACEHOLDER}}` and the repeat-block patterns; that comment
  is stripped at render time so it never ships publicly.
- **Where they live:** the `site/` git repo (deployed to GitHub Pages), under
  `site/plaene/<slug>.html`. The `plaene/` directory carries `noindex,nofollow`
  via the template's robots meta, and the whole page is unindexed.
- **Unguessable slugs:** each page filename is 12 hex chars from `uuid4()`, so
  the URL cannot be guessed (`.../golfausflug-funnel/plaene/<12hex>.html`).
- **Plan-Nr.:** each page shows a `ZA-XXXXX` plan id (5 uppercase alphanumerics).
- **Publish flow:** render -> write file -> `git add/commit/push` in `site/` ->
  poll the live URL every 15s (up to 4 min) until HTTP 200 -> insert the link
  into the plan email (text + html). If page generation or publishing fails for
  ANY reason, the email is sent **without** the link, never blocking the lead.
- **State:** the lead's record in `state.json` stores `page_url` + `plan_id`.

## How to pause

```
touch /Users/jonathanschoenberg/.claude/scripts/golfausflug-funnel/PAUSED-GOLFAUSFLUG
```

While that file exists the loop logs `paused` and exits without doing anything.
Delete it to resume.

## How to watch

- `runs.log` - `timestamp | new_leads=N | replies=N | duration=Xs | status`
- `state.json` - current per-lead state
- `launchd.log` - stdout/stderr of the scheduled runs
- On any unhandled error the loop self-notifies via one `[AI]` email (send-email.sh).

## Install (director loads this AFTER the end-to-end test)

The plist is written to this script dir but is **not** loaded automatically.
Copy or symlink it into LaunchAgents, then load:

```
cp /Users/jonathanschoenberg/.claude/scripts/golfausflug-funnel/com.golfausflug.funnel-loop.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.golfausflug.funnel-loop.plist
```

It then runs every 5 minutes (StartInterval 300) and at load.

## Dry test

```
python3 golfausflug-loop.py --dry-run
```

Does everything except claude calls and sending (prints what it WOULD do).
