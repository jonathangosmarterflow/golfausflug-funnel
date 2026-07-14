#!/usr/bin/env python3
"""
golfausflug-loop.py - Autonomous email engine for the Golfausflug funnel.

Demo AI system for goHartl golftours (golfausflug.de): German golf trips to
South Africa. Polls a Google Form for new leads, generates a personalized
German trip plan with Claude, emails it, and runs up to 15 refinement reply
rounds on each thread before handing off to Gerd Schoenberg.

COMPLETELY SEPARATE from the SmarterFlow estimate funnel. stdlib only; shells
out to `gws` (Google Workspace CLI) and `claude` (Claude Code CLI).

Run:  python3 golfausflug-loop.py            (live)
      python3 golfausflug-loop.py --dry-run  (no claude calls, no sending)
"""

import base64
import html as html_mod
import json
import os
import random
import re
import string
import subprocess
import sys
import time
import traceback
import urllib.request
import uuid
from datetime import datetime, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid, formatdate

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_FILE = os.path.join(SCRIPT_DIR, "trip-knowledge.md")
STATE_FILE = os.path.join(SCRIPT_DIR, "state.json")
RUNS_LOG = os.path.join(SCRIPT_DIR, "runs.log")
PAUSE_FILE = os.path.join(SCRIPT_DIR, "PAUSED-GOLFAUSFLUG")
LOCK_FILE = os.path.join(SCRIPT_DIR, ".golfausflug-loop.lock")
SEND_EMAIL_SH = "/Users/jonathanschoenberg/.claude/skills/daily-dream/send-email.sh"

# Trip-page publishing (the site/ subdir is its own git repo -> GitHub Pages)
TEMPLATE_FILE = os.path.join(SCRIPT_DIR, "trip-page-template.html")
SITE_DIR = os.path.join(SCRIPT_DIR, "site")
PLAENE_DIR = os.path.join(SITE_DIR, "plaene")
PAGE_BASE_URL = "https://jonathangosmarterflow.github.io/golfausflug-funnel/plaene/"
PAGE_POLL_TIMEOUT = 240   # seconds (4 min)
PAGE_POLL_INTERVAL = 15   # seconds
GERMAN_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                 "August", "September", "Oktober", "November", "Dezember"]

FORM_ID = "1dxA3uqRyML4LUSr3494HbKv6vDjHLgdUBj0Cid4lVkU"
LABEL_NAME = "Golfausflug-Funnel"
FROM_HEADER = "Golfausflug Suedafrika-Reiseplaner <jonathan@gosmarterflow.com>"
SENDER_EMAIL = "jonathan@gosmarterflow.com"
MAX_ROUNDS = 15
PARTIAL_HOLD_MIN = 15
FOLLOWUP_AFTER_DAYS = 3
CLAUDE_MODEL = "claude-opus-4-8"

# questionId -> field name
Q = {
    "7b5a48a0": "Vorname",
    "53d246e9": "Nachname",
    "171e7a7f": "E-Mail",
    "1584b817": "Reisezeitraum",
    "63d9710d": "Reisedauer",
    "35ef8ead": "Abflughafen",
    "7e404d67": "Golf-Frequenz",
    "7b7a3836": "Interessen",
    "248e2811": "Reisebegleitung",
    "4b84a7fd": "Mobilitaet",
    "16e27bd0": "Spielstaerke",
    "3b0dae78": "Budget",
    "3aa52425": "Anmerkungen",
}

DRY_RUN = "--dry-run" in sys.argv


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
def log(msg):
    print(f"[golfausflug] {msg}", flush=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_knowledge():
    """Read trip-knowledge.md at RUNTIME. If missing, wait+retry up to 3x."""
    for attempt in range(3):
        if os.path.exists(KNOWLEDGE_FILE):
            with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as fh:
                return fh.read()
        log(f"trip-knowledge.md missing (attempt {attempt + 1}/3), waiting 60s...")
        time.sleep(60 if not DRY_RUN else 1)
    log("WARNING: trip-knowledge.md still missing; proceeding with empty KB.")
    return ""


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            log(f"state.json unreadable ({exc}); starting fresh.")
    return {"processed_response_ids": [], "leads": {}, "label_id": None}


def save_state(state):
    if DRY_RUN:
        return
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def migrate_state(state):
    """Backfill fields added by later upgrades onto existing lead entries.

    Idempotent. sent_message_ids seeds from the known last message id so a
    pre-upgrade lead's original plan message is recognized as engine-sent (and
    therefore never mistaken for a lead reply). plan_sent_time backfills to the
    last-updated time so the 3-day follow-up clock is anchored sensibly.
    """
    changed = False
    for lead in state.get("leads", {}).values():
        if "sent_message_ids" not in lead:
            smi = []
            if lead.get("lastMessageId"):
                smi.append(lead["lastMessageId"])
            lead["sent_message_ids"] = smi
            changed = True
        if "plan_sent_time" not in lead:
            lead["plan_sent_time"] = lead.get("updated") or now_iso()
            changed = True
        if "followup_sent" not in lead:
            lead["followup_sent"] = False
            changed = True
    if changed:
        save_state(state)
    return state


def ensure_gws_on_path():
    """launchd runs with a minimal PATH that lacks the nvm node bin, so `gws`
    is not found and the loop crashes. If gws is not resolvable, prepend the
    first dir that actually contains it. No-op when gws is already on PATH."""
    import shutil
    if shutil.which("gws"):
        return
    candidates = []
    nvm = os.path.expanduser("~/.nvm/versions/node")
    if os.path.isdir(nvm):
        for ver in sorted(os.listdir(nvm), reverse=True):
            candidates.append(os.path.join(nvm, ver, "bin"))
    candidates.append(os.path.expanduser("~/.local/bin"))
    candidates.append("/usr/local/bin")
    for c in candidates:
        if os.path.exists(os.path.join(c, "gws")):
            os.environ["PATH"] = c + os.pathsep + os.environ.get("PATH", "")
            log(f"gws not on PATH; prepended {c}")
            return
    log("WARNING: gws not found on PATH and no fallback dir contained it.")


def append_run_log(new_leads, replies, followups, duration, status):
    line = (f"{now_iso()} | new_leads={new_leads} | replies={replies} "
            f"| followups={followups} | duration={duration:.1f}s | status={status}\n")
    if DRY_RUN:
        log("would append runs.log: " + line.strip())
        return
    with open(RUNS_LOG, "a", encoding="utf-8") as fh:
        fh.write(line)


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------
def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as fh:
                old_pid = int(fh.read().strip())
            os.kill(old_pid, 0)  # raises if not running
            log(f"another instance running (pid {old_pid}); exiting.")
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            log("stale lock found; overwriting.")
        except Exception:
            log("stale lock (unknown); overwriting.")
    with open(LOCK_FILE, "w") as fh:
        fh.write(str(os.getpid()))
    return True


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# gws helpers
# ---------------------------------------------------------------------------
def gws(args, body=None, params=None):
    """Run a gws command, return parsed JSON (or None)."""
    cmd = ["gws"] + args
    if params is not None:
        cmd += ["--params", json.dumps(params)]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gws {' '.join(args)} failed: {res.stderr.strip()}")
    out = res.stdout.strip()
    # gws prints a keyring backend line before JSON sometimes.
    brace = out.find("{")
    bracket = out.find("[")
    starts = [p for p in (brace, bracket) if p != -1]
    if not starts:
        return None
    return json.loads(out[min(starts):])


def poll_responses():
    data = gws(["forms", "forms", "responses", "list"], params={"formId": FORM_ID})
    return (data or {}).get("responses", [])


def ensure_label(state):
    if state.get("label_id"):
        return state["label_id"]
    data = gws(["gmail", "users", "labels", "list"], params={"userId": "me"})
    for lbl in (data or {}).get("labels", []):
        if lbl.get("name") == LABEL_NAME:
            state["label_id"] = lbl["id"]
            return lbl["id"]
    if DRY_RUN:
        log(f"would create label '{LABEL_NAME}'")
        return None
    created = gws(["gmail", "users", "labels", "create"], params={"userId": "me"},
                  body={"name": LABEL_NAME, "labelListVisibility": "labelShow",
                        "messageListVisibility": "show"})
    state["label_id"] = created["id"]
    return created["id"]


def apply_label(thread_id, label_id):
    if not thread_id or not label_id or DRY_RUN:
        return
    try:
        gws(["gmail", "users", "threads", "modify"],
            params={"userId": "me", "id": thread_id},
            body={"addLabelIds": [label_id]})
    except Exception as exc:
        log(f"label apply failed for {thread_id}: {exc}")


# ---------------------------------------------------------------------------
# Lead parsing
# ---------------------------------------------------------------------------
def parse_answers(response):
    answers = response.get("answers", {})
    out = {}
    for qid, field in Q.items():
        val = ""
        node = answers.get(qid)
        if node:
            ta = node.get("textAnswers", {}).get("answers", [])
            if ta:
                val = ta[0].get("value", "")
        out[field] = val.strip()
    return out


def created_dt(response):
    ct = response.get("createTime", "")
    try:
        return datetime.fromisoformat(ct.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Claude generation
# ---------------------------------------------------------------------------
VOICE_RULES = (
    "HARTE REGELN: Kein Gedankenstrich (—) verwenden, nirgends. Nur direkte "
    "saubere URLs (https://www.golfausflug.de/...). KEINE Erwaehnung von "
    "SmarterFlow. Ausschliesslich Deutsch, durchgehende Sie-Form. Ton: "
    "authentisch, familiaer und mit ganz viel Herz. Kein Hype, keine "
    "Superlative-Schlacht, keine Ausrufezeichen-Flut. "
    "WICHTIG: Im gesamten E-Mail-Text (subject, body_text, body_html) IMMER "
    "korrekte deutsche Umlaute und Eszett verwenden (ä, ö, ü, Ä, Ö, Ü, ß) — "
    "NIEMALS Umschreibungen wie ae, oe, ue, ss (also 'für', 'Südafrika', "
    "'Grüße', nicht 'fuer', 'Suedafrika', 'Gruesse')."
)


def build_plan_prompt(kb, fields, abandoned=False, include_page=False):
    lead_block = "\n".join(f"- {k}: {v or 'nicht angegeben'}" for k, v in fields.items())
    vorname = fields.get("Vorname") or "Golffreund"
    if abandoned:
        task = (
            "Der Gast hat das Formular nur teilweise ausgefuellt (abgebrochen). "
            "Schreibe eine KUERZERE, herzliche Einladungs-E-Mail: persoenliche "
            "Anrede mit Vorname, 2-3 Saetze, warum eine Suedafrika-Golfreise ein "
            "Traum ist, ein kurzer Hinweis auf die gefuehrten Gruppenreisen mit "
            "Gerd, und die klare Einladung, einfach auf diese E-Mail zu antworten "
            "und ihre Wuensche zu schildern (Reisezeit, Dauer, Budget, Interessen), "
            "damit wir einen individuellen Plan erstellen koennen. Keine volle "
            "Reiseplanung, kein Tag-fuer-Tag."
        )
    else:
        task = (
            "Schreibe eine warme, persoenliche deutsche E-Mail mit:\n"
            "1. Persoenliche Anrede mit Vorname.\n"
            "2. 2-Satz-Intro.\n"
            "3. Tag-fuer-Tag-Reiseverlauf (Tag 1, Tag 2, ...) passend zu "
            "Reisedauer/Interessen/Golf-Frequenz. NUR echte Plaetze/Hotels/Regionen "
            "aus der Wissensbasis, mit realistischer Routenfuehrung (kein Zickzack, "
            "echte Fahrzeiten respektieren).\n"
            "4. Ein Preis-Absatz: 'Grober Preisrahmen: ab X bis Y Euro pro Person "
            "(ohne Fluege)', berechnet aus der Preis-Logik der Wissensbasis "
            "(Zieltage x EUR/Tag, ggf. Mietwagen/Tag, ggf. EZ-Zuschlag).\n"
            "5. EIN warmer Absatz zu den gefuehrten Gruppenreisen als Alternative "
            "(Bus statt Mietwagen, Weinproben ohne Fahren, soziales Miteinander, "
            "null Planungsstress, PGA Professional Gerd Schoenberg). Nenne 1-2 echte "
            "kommende Reisen mit Datum + ab-Preis, die am besten zu den Antworten "
            "des Gastes passen.\n"
            "6. Abschluss: Einladung, einfach auf diese E-Mail zu ANTWORTEN mit "
            "Aenderungswuenschen ('mehr Safari, weniger Golf, anderes Budget, "
            "antworten Sie einfach')."
        )
    if include_page:
        page_instr = (
            "\n\nZUSAETZLICH: Erzeuge ein \"page\"-Objekt fuer eine persoenliche "
            "Reiseplan-Webseite, die GENAU zur selben Reise wie die E-Mail passt "
            "(gleiche Plaetze, Hotels, Tage, Preisrahmen). Struktur des page-Objekts:\n"
            "  \"titel\": kurzer, poetischer Reisetitel, z.B. \"Golf, Safari und Kapstadt im November\"\n"
            "  \"zeitraum\": z.B. \"Februar 2027\"\n"
            "  \"dauer\": z.B. \"14 Tage\"\n"
            "  \"abflug\": z.B. \"ab Frankfurt\"\n"
            "  \"reisende\": z.B. \"Mit Freunden\"\n"
            "  \"preis_range\": z.B. \"3.600 bis 4.400 € pro Person\"\n"
            "  \"preis_hinweis\": z.B. \"ohne internationale Fluege\"\n"
            "  \"highlights\": Liste von {\"icon\": \"⛳\", \"text\": \"7 Golfrunden\"} (MAX 6, je ein passendes Emoji)\n"
            "  \"days\": Liste von {\"n\": 1, \"icon\": \"✈️\", \"titel\": \"...\", \"text\": \"1-2 Saetze\"} (ein Eintrag pro Reisetag)\n"
            "  \"hotels\": Liste von {\"name\": \"...\", \"meta\": \"Ort · Kategorie · N Naechte\"}\n"
            "  \"hinweise\": Liste von 4-6 praktischen Reisehinweisen fuer Suedafrika (Text pur)\n"
            "  \"inklusive\": Liste, was im Preis enthalten ist\n"
            "  \"exklusive\": Liste, was NICHT enthalten ist\n"
            "Icons fuer days: ⛳ Golf, 🦁 Safari, 🍷 Wein, 🐋 Wale, 🏖 Strand, 🚐 Fahrt, ✈️ Flug, 🌆 Stadt.\n"
            "Nur echte Plaetze/Hotels/Regionen aus der Wissensbasis. Fuer den gesamten page-"
            "Inhalt gelten dieselben Sprachregeln: korrekte Umlaute (ä ö ü ß), kein "
            "Gedankenstrich, Sie-Form.")
        json_line = ('{{"subject": "...", "body_text": "...", "body_html": "...", '
                     '"page": {{ "titel": "...", "zeitraum": "...", "dauer": "...", '
                     '"abflug": "...", "reisende": "...", "preis_range": "...", '
                     '"preis_hinweis": "...", "highlights": [...], "days": [...], '
                     '"hotels": [...], "hinweise": [...], "inklusive": [...], '
                     '"exklusive": [...] }} }}')
    else:
        page_instr = ""
        json_line = '{{"subject": "...", "body_text": "...", "body_html": "..."}}'

    return f"""Du bist der Suedafrika-Reiseplaner von goHartl golftours (golfausflug.de).

Nutze AUSSCHLIESSLICH die folgende Wissensbasis als Quelle der Wahrheit:

===== WISSENSBASIS =====
{kb}
===== ENDE WISSENSBASIS =====

Angaben des Gastes:
{lead_block}

{task}

Signatur am Ende:
Herzliche Gruesse,
Ihr Golfausflug Suedafrika-Reiseplaner
goHartl golftours . Gerd Schoenberg . golfausflug.de

{VOICE_RULES}

Betreff-Format: "Ihr persoenlicher Suedafrika-Reiseplan, {vorname}" (ein Golf-Emoji als Prefix ist erlaubt).
{page_instr}

Gib das Ergebnis als STRIKTES JSON zurueck, NUR das JSON-Objekt, keine weiteren Worte:
{json_line}
- body_text: reiner Text mit Zeilenumbruechen.
- body_html: einfache <div>/<br>-Struktur, umschlossen von
  <div dir="ltr" style="font-family:Arial,Helvetica,sans-serif;font-size:14px">...</div>
  ohne weiteres Styling, keine grossen Schriften."""


def build_reply_prompt(kb, fields, conversation, lead_message):
    lead_block = "\n".join(f"- {k}: {v or 'nicht angegeben'}" for k, v in fields.items())
    vorname = fields.get("Vorname") or "Golffreund"
    return f"""Du bist der Suedafrika-Reiseplaner von goHartl golftours (golfausflug.de).

Nutze AUSSCHLIESSLICH die folgende Wissensbasis als Quelle der Wahrheit:

===== WISSENSBASIS =====
{kb}
===== ENDE WISSENSBASIS =====

Urspruengliche Angaben des Gastes:
{lead_block}

Bisheriger Gespraechs-Kontext (gekuerzt):
{conversation}

Neue Nachricht / Wuensche des Gastes:
{lead_message}

Schreibe eine FOKUSSIERTE Antwort-E-Mail (kein kompletter Neu-Pitch): gehe warm
und persoenlich auf die neuen Wuensche ein, passe den Plan gezielt an (nur echte
Plaetze/Hotels/Regionen aus der Wissensbasis, realistische Routen/Fahrzeiten),
aktualisiere wo noetig den groben Preisrahmen ('ab X bis Y Euro pro Person, ohne
Fluege') und lade erneut ein, einfach mit weiteren Aenderungswuenschen zu antworten.

Signatur am Ende:
Herzliche Gruesse,
Ihr Golfausflug Suedafrika-Reiseplaner
goHartl golftours . Gerd Schoenberg . golfausflug.de

{VOICE_RULES}

Gib das Ergebnis als STRIKTES JSON zurueck, NUR das JSON-Objekt:
{{"subject": "Re: ...", "body_text": "...", "body_html": "..."}}
- body_html: einfache <div>/<br>-Struktur, umschlossen von
  <div dir="ltr" style="font-family:Arial,Helvetica,sans-serif;font-size:14px">...</div>"""


def call_claude(prompt):
    res = subprocess.run(
        ["claude", "-p", "--model", CLAUDE_MODEL],
        input=prompt, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"claude failed: {res.stderr.strip()[:500]}")
    return parse_claude_json(res.stdout)


def parse_claude_json(raw):
    text = raw.strip()
    if "```" in text:  # strip markdown fences
        parts = text.split("```")
        for part in parts:
            p = part.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                text = p
                break
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in claude output: {raw[:300]}")
    obj = json.loads(text[start:end + 1])
    if "subject" not in obj or "body_text" not in obj:
        raise ValueError("claude JSON missing required keys")
    obj.setdefault("body_html", None)
    return obj


# ---------------------------------------------------------------------------
# Personalized trip page (rendered from trip-page-template.html, published to
# the site/ git repo -> GitHub Pages under an unguessable plaene/<slug>.html)
# ---------------------------------------------------------------------------
def german_date_today():
    now = datetime.now()
    return f"{now.day}. {GERMAN_MONTHS[now.month - 1]} {now.year}"


def gen_plan_id():
    alphabet = string.ascii_uppercase + string.digits
    return "ZA-" + "".join(random.choice(alphabet) for _ in range(5))


def render_trip_page(page, vorname):
    """Fill trip-page-template.html from the claude `page` object.

    Builds the repeat-block HTML exactly per the template's header-comment
    patterns, HTML-escaping all dynamic values, and replaces every placeholder.
    Returns (plan_id, html)."""
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as fh:
        tpl = fh.read()
    # Strip the template's internal documentation comment (it documents the
    # placeholders and is not meant to ship on the public page).
    tpl = re.sub(r"^\s*<!--.*?-->\s*", "", tpl, count=1, flags=re.DOTALL)
    plan_id = gen_plan_id()
    page = page or {}

    def esc(v):
        return html_mod.escape(str(v if v is not None else ""))

    highlights_html = "".join(
        f'<span class="hl-chip">{esc(h.get("icon", ""))} {esc(h.get("text", ""))}</span>'
        for h in (page.get("highlights") or [])[:6])

    days_html = "".join(
        '<li class="day">'
        f'<span class="d-marker"><b>Tag {esc(d.get("n", ""))}</b>'
        f'<i>{esc(d.get("icon", ""))}</i></span>'
        '<div class="d-body">'
        f'<h3>{esc(d.get("titel", ""))}</h3>'
        f'<p>{esc(d.get("text", ""))}</p>'
        '</div></li>'
        for d in (page.get("days") or []))

    hotels_html = "".join(
        f'<div class="hotel"><b>{esc(h.get("name", ""))}</b>'
        f'<span>{esc(h.get("meta", ""))}</span></div>'
        for h in (page.get("hotels") or []))

    hinweise_html = "".join(f"<li>{esc(x)}</li>" for x in (page.get("hinweise") or []))
    inklusive_html = "".join(f"<li>{esc(x)}</li>" for x in (page.get("inklusive") or []))
    exklusive_html = "".join(f"<li>{esc(x)}</li>" for x in (page.get("exklusive") or []))

    repl = {
        "{{VORNAME}}": esc(vorname or "Golffreund"),
        "{{TITEL}}": esc(page.get("titel", "")),
        "{{ZEITRAUM}}": esc(page.get("zeitraum", "")),
        "{{DAUER}}": esc(page.get("dauer", "")),
        "{{ABFLUG}}": esc(page.get("abflug", "")),
        "{{REISENDE}}": esc(page.get("reisende", "")),
        "{{PREIS_RANGE}}": esc(page.get("preis_range", "")),
        "{{PREIS_HINWEIS}}": esc(page.get("preis_hinweis", "")),
        "{{DATUM}}": german_date_today(),
        "{{PLAN_ID}}": plan_id,
        "{{DAYS_HTML}}": days_html,
        "{{HOTELS_HTML}}": hotels_html,
        "{{HIGHLIGHTS_HTML}}": highlights_html,
        "{{HINWEISE_HTML}}": hinweise_html,
        "{{INKLUSIVE_HTML}}": inklusive_html,
        "{{EXKLUSIVE_HTML}}": exklusive_html,
    }
    for key, val in repl.items():
        tpl = tpl.replace(key, val)
    return plan_id, tpl


def _git_site(args):
    res = subprocess.run(["git"] + args, cwd=SITE_DIR,
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res


def publish_trip_page(html_content, slug, plan_id):
    """Write site/plaene/<slug>.html, commit + push, then poll GitHub Pages
    until the URL returns 200 (up to 4 min). Returns the URL, or None on
    timeout/failure."""
    if DRY_RUN:
        log(f"[dry-run] would publish trip page plaene/{slug}.html")
        return None
    os.makedirs(PLAENE_DIR, exist_ok=True)
    path = os.path.join(PLAENE_DIR, slug + ".html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html_content)
    rel = f"plaene/{slug}.html"
    _git_site(["add", rel])
    _git_site(["commit", "-m", f"Reiseplan {plan_id}"])
    _git_site(["push"])

    url = PAGE_BASE_URL + slug + ".html"
    deadline = time.time() + PAGE_POLL_TIMEOUT
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                if resp.status == 200:
                    log(f"trip page live (200): {url}")
                    return url
        except Exception:
            pass
        time.sleep(PAGE_POLL_INTERVAL)
    log(f"WARNING: trip page did not reach 200 within "
        f"{PAGE_POLL_TIMEOUT}s: {url}")
    return None


_PAGE_LINK_LABEL = ("Ihren vollständigen Reiseplan als übersichtliche Seite "
                    "finden Sie hier:")


def insert_page_link_text(body_text, url):
    block = f"{_PAGE_LINK_LABEL}\n{url}"
    paras = body_text.split("\n\n")
    if len(paras) >= 2:
        paras.insert(1, block)   # after the greeting, near the top
    else:
        paras.insert(0, block)
    return "\n\n".join(paras)


def insert_page_link_html(body_html, url):
    link = (f'<br>{_PAGE_LINK_LABEL} '
            f'<a href="{url}">{url}</a><br>')
    for sep in ("<br><br>", "<br>"):
        idx = body_html.find(sep)
        if idx != -1:
            pos = idx + len(sep)
            return body_html[:pos] + link + body_html[pos:]
    m = re.search(r"<div[^>]*>", body_html)
    if m:
        return body_html[:m.end()] + link + body_html[m.end():]
    return link + body_html


# ---------------------------------------------------------------------------
# Email building + sending
# ---------------------------------------------------------------------------
def build_raw(to_email, subject, body_text, body_html, in_reply_to=None):
    msg = MIMEMultipart("alternative")
    msg["From"] = FROM_HEADER
    msg["To"] = to_email
    # Encode non-ASCII (umlaut) subjects so as_bytes() never raises.
    try:
        subject.encode("ascii")
        msg["Subject"] = subject
    except UnicodeEncodeError:
        msg["Subject"] = Header(subject, "utf-8")
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gosmarterflow.com")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    if not body_html:
        safe = body_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body_html = ('<div dir="ltr" style="font-family:Arial,Helvetica,sans-serif;'
                     'font-size:14px">' + safe.replace("\n", "<br>") + "</div>")
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return raw


def send_message(raw, thread_id=None):
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    result = gws(["gmail", "users", "messages", "send"],
                 params={"userId": "me"}, body=body)
    return result  # {id, threadId, ...}


# ---------------------------------------------------------------------------
# Thread reading (for reply rounds)
# ---------------------------------------------------------------------------
def get_thread_full(thread_id):
    return gws(["gmail", "users", "threads", "get"],
               params={"userId": "me", "id": thread_id, "format": "full"})


def header_value(payload, name):
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def extract_text(payload):
    """Walk MIME parts, return decoded text/plain (fallback text/html stripped)."""
    def walk(part):
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if mime == "text/plain" and data:
            return b64d(data)
        for sub in part.get("parts", []):
            found = walk(sub)
            if found:
                return found
        if mime == "text/html" and data:
            html = b64d(data)
            # crude strip
            import re
            return re.sub(r"<[^>]+>", " ", html)
        return ""
    return walk(payload).strip()


def b64d(data):
    try:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace")
    except Exception:
        return ""


def newest_message(thread):
    msgs = thread.get("messages", [])
    if not msgs:
        return None
    # messages are in ascending order; take last
    return msgs[-1]


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
def process_new_leads(state, kb, responses):
    """Returns count of new plan emails sent."""
    processed = set(state["processed_response_ids"])
    leads = state["leads"]
    label_id = ensure_label(state)

    # Bucket unprocessed, non-test responses by email
    complete_by_email = {}   # email -> (response, fields)
    partial_by_email = {}    # email -> list of (response, fields)

    for resp in responses:
        rid = resp.get("responseId")
        if rid in processed:
            continue
        fields = parse_answers(resp)
        anmerk = fields.get("Anmerkungen", "")
        if "PIPELINE-TEST" in anmerk:
            log(f"skipping test row (responseId {rid[:12]}...)")
            processed.add(rid)
            state["processed_response_ids"].append(rid)
            continue
        email = (fields.get("E-Mail") or "").strip().lower()
        if not email:
            log(f"skipping row with no email (responseId {rid[:12]}...)")
            processed.add(rid)
            state["processed_response_ids"].append(rid)
            continue
        if "PARTIAL" in anmerk:
            partial_by_email.setdefault(email, []).append((resp, fields))
        else:
            # keep the newest complete per email
            prev = complete_by_email.get(email)
            if not prev or created_dt(resp) > created_dt(prev[0]):
                complete_by_email[email] = (resp, fields)

    sent = 0

    # 1) Complete rows (new lead OR refreshed-plan update on existing thread)
    for email, (resp, fields) in complete_by_email.items():
        rid = resp.get("responseId")
        existing = leads.get(email)
        if existing and existing.get("threadId"):
            # Later row for an already-served lead -> refreshed plan REPLY
            log(f"refreshed plan (update) for existing lead {email}")
            ok = generate_and_send_plan(state, kb, email, fields,
                                        update_existing=True)
            sent += 1 if ok else 0
        else:
            log(f"new complete lead {email}")
            ok = generate_and_send_plan(state, kb, email, fields,
                                        update_existing=False)
            sent += 1 if ok else 0
        # mark this + any partials for same email processed
        _mark_processed(state, processed, rid)
        for presp, _ in partial_by_email.get(email, []):
            _mark_processed(state, processed, presp.get("responseId"))
        partial_by_email.pop(email, None)
        apply_label(leads.get(email, {}).get("threadId"), label_id)

    # 2) Partial rows with no complete counterpart -> hold 15 min, then abandoned
    now = datetime.now(timezone.utc)
    for email, plist in partial_by_email.items():
        if email in leads:  # already served -> just mark processed
            for presp, _ in plist:
                _mark_processed(state, processed, presp.get("responseId"))
            continue
        # use the newest partial
        presp, pfields = max(plist, key=lambda t: created_dt(t[0]))
        age_min = (now - created_dt(presp)).total_seconds() / 60.0
        if age_min >= PARTIAL_HOLD_MIN:
            log(f"partial matured ({age_min:.0f}min) -> abandoned lead {email}")
            ok = generate_and_send_plan(state, kb, email, pfields,
                                        update_existing=False, abandoned=True)
            sent += 1 if ok else 0
            for p2, _ in plist:
                _mark_processed(state, processed, p2.get("responseId"))
            apply_label(leads.get(email, {}).get("threadId"), label_id)
        else:
            log(f"holding partial {email} ({age_min:.0f}/{PARTIAL_HOLD_MIN}min)")

    save_state(state)
    return sent


def _mark_processed(state, processed_set, rid):
    if rid and rid not in processed_set:
        processed_set.add(rid)
        state["processed_response_ids"].append(rid)


def generate_and_send_plan(state, kb, email, fields, update_existing, abandoned=False):
    leads = state["leads"]
    # A personalized trip PAGE is generated ONLY for a brand-new complete lead
    # (not refinements, not abandoned/partial invites, not follow-ups).
    want_page = (not update_existing) and (not abandoned)
    prompt = build_plan_prompt(kb, fields, abandoned=abandoned, include_page=want_page)
    if DRY_RUN:
        kind = "abandoned invite" if abandoned else (
            "refreshed plan" if update_existing else "plan")
        extra = " (+ trip page)" if want_page else ""
        log(f"[dry-run] would call claude + send {kind}{extra} to {email}")
        return True
    try:
        gen = call_claude(prompt)
    except Exception as exc:
        log(f"claude generation failed for {email}: {exc}")
        return False

    # Generate + publish the personalized trip page BEFORE sending the email.
    # Any failure here NEVER blocks the lead flow: log a warning, send without
    # the link.
    page_url = None
    plan_id = None
    if want_page:
        try:
            page_obj = gen.get("page")
            if page_obj:
                plan_id, page_html = render_trip_page(
                    page_obj, fields.get("Vorname", ""))
                slug = uuid.uuid4().hex[:12]
                page_url = publish_trip_page(page_html, slug, plan_id)
                if not page_url:
                    log(f"trip page publish did not confirm live for {email}; "
                        f"sending email without link")
            else:
                log(f"claude returned no page object for {email}; "
                    f"sending email without link")
        except Exception as exc:
            log(f"trip page generation/publish failed for {email}: {exc}; "
                f"sending email without link")
            page_url = None

    if page_url:
        gen["body_text"] = insert_page_link_text(gen["body_text"], page_url)
        if gen.get("body_html"):
            gen["body_html"] = insert_page_link_html(gen["body_html"], page_url)

    thread_id = leads.get(email, {}).get("threadId") if update_existing else None
    in_reply_to = None
    subject = gen["subject"]
    if update_existing and thread_id:
        # send as reply on existing thread
        try:
            thread = get_thread_full(thread_id)
            nm = newest_message(thread)
            if nm:
                in_reply_to = header_value(nm["payload"], "Message-ID")
        except Exception:
            pass
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject

    raw = build_raw(email, subject, gen["body_text"], gen.get("body_html"),
                    in_reply_to=in_reply_to)
    result = send_message(raw, thread_id=thread_id)
    tid = result.get("threadId", thread_id)
    mid = result.get("id")

    lead = leads.get(email, {})
    smi = lead.get("sent_message_ids", [])
    if mid and mid not in smi:
        smi.append(mid)
    lead.update({
        "email": email,
        "vorname": fields.get("Vorname", ""),
        "threadId": tid,
        "rounds": lead.get("rounds", 0),
        "lastMessageId": mid,
        "sent_message_ids": smi,
        "plan_sent_time": lead.get("plan_sent_time") or now_iso(),
        "followup_sent": lead.get("followup_sent", False),
        "status": lead.get("status", "active"),
        "abandoned": abandoned or lead.get("abandoned", False),
        "updated": now_iso(),
    })
    if page_url:
        lead["page_url"] = page_url
    if plan_id:
        lead["plan_id"] = plan_id
    leads[email] = lead
    log(f"sent {'refreshed ' if update_existing else ''}plan to {email} "
        f"(thread {tid})")
    return True


def process_reply_rounds(state, kb):
    """Returns count of reply emails sent."""
    leads = state["leads"]
    replies = 0
    for email, lead in leads.items():
        if lead.get("status") != "active":
            continue
        if lead.get("rounds", 0) >= MAX_ROUNDS:
            continue
        thread_id = lead.get("threadId")
        if not thread_id:
            continue
        try:
            thread = get_thread_full(thread_id) if not DRY_RUN else None
        except Exception as exc:
            log(f"thread fetch failed {email}: {exc}")
            continue
        if DRY_RUN:
            log(f"[dry-run] would check thread {thread_id} for {email} "
                f"(round {lead.get('rounds',0)})")
            continue

        nm = newest_message(thread)
        if not nm:
            continue
        nm_id = nm.get("id")
        # A lead reply = the newest thread message whose id is NOT one the engine
        # itself sent (tracked in sent_message_ids). This is robust even when the
        # lead's From address == our own sender address (self-test with
        # jonathan@), where a From-based check would wrongly skip every reply.
        sent_ids = lead.get("sent_message_ids", [])
        if nm_id in sent_ids or nm_id == lead.get("lastMessageId"):
            continue

        lead_text = extract_text(nm["payload"])[:4000]
        msg_id_hdr = header_value(nm["payload"], "Message-ID")
        # brief conversation context: subjects/snippets of prior messages
        convo = []
        for m in thread.get("messages", [])[-6:]:
            snip = m.get("snippet", "")
            convo.append(snip)
        conversation = "\n---\n".join(convo)[:3000]

        prompt = build_reply_prompt(kb, {
            "Vorname": lead.get("vorname", ""),
        }, conversation, lead_text)
        try:
            gen = call_claude(prompt)
        except Exception as exc:
            log(f"claude reply gen failed {email}: {exc}")
            continue

        subject = gen["subject"]
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject
        body_text = gen["body_text"]
        body_html = gen.get("body_html")

        new_rounds = lead.get("rounds", 0) + 1
        if new_rounds >= MAX_ROUNDS:
            handoff = ("\n\nDamit Ihr Plan perfekt wird, uebernimmt ab hier Gerd "
                       "Schoenberg persoenlich (info@golfausflug.de).")
            body_text = body_text.rstrip() + handoff
            if body_html:
                body_html = body_html.replace(
                    "</div>", "<br><br>" + handoff.strip().replace("\n", "<br>")
                    + "</div>", 1) if "</div>" in body_html else body_html

        raw = build_raw(email, subject, body_text, body_html,
                        in_reply_to=msg_id_hdr)
        result = send_message(raw, thread_id=thread_id)
        lead["rounds"] = new_rounds
        new_mid = result.get("id")
        lead["lastMessageId"] = new_mid
        smi = lead.get("sent_message_ids", [])
        if new_mid and new_mid not in smi:
            smi.append(new_mid)
        lead["sent_message_ids"] = smi
        lead["updated"] = now_iso()
        if new_rounds >= MAX_ROUNDS:
            lead["status"] = "handed_off"
            log(f"round {new_rounds}: handed off {email} to Gerd")
        else:
            log(f"sent refinement reply round {new_rounds} to {email}")
        replies += 1
        save_state(state)
    return replies


def process_followups(state):
    """Send exactly ONE short 3-day reminder to each lead who got a plan but
    never replied (rounds == 0, no follow-up yet). Fixed German template, no
    claude call. Returns count of follow-ups sent."""
    leads = state["leads"]
    now = datetime.now(timezone.utc)
    sent = 0
    for email, lead in leads.items():
        if lead.get("status") != "active":
            continue
        if lead.get("rounds", 0) != 0:
            continue
        if lead.get("followup_sent"):
            continue
        thread_id = lead.get("threadId")
        if not thread_id:
            continue
        pst = lead.get("plan_sent_time")
        try:
            pst_dt = datetime.fromisoformat(pst) if pst else now
        except Exception:
            pst_dt = now
        age_days = (now - pst_dt).total_seconds() / 86400.0
        if age_days < FOLLOWUP_AFTER_DAYS:
            continue

        if DRY_RUN:
            log(f"[dry-run] would send 3-day follow-up to {email} "
                f"(age {age_days:.1f}d)")
            lead["followup_sent"] = True
            continue

        vorname = lead.get("vorname") or "Golffreund"
        subject = "Re: Ihr persönlicher Südafrika-Reiseplan"
        body_text = (
            f"Hallo {vorname},\n\n"
            "ich wollte kurz nachhören, ob Ihr Reiseplan Ihren Vorstellungen "
            "entspricht.\n\n"
            "Falls Sie sich noch etwas anderes wünschen, antworten Sie einfach "
            "auf diese E-Mail mit Ihren Wünschen, dann passe ich den Plan gerne "
            "für Sie an.\n\n"
            "Ich freue mich, von Ihnen zu hören.\n\n"
            "Herzliche Grüße,\n"
            "Ihr Golfausflug Südafrika-Reiseplaner"
        )
        in_reply_to = None
        try:
            thread = get_thread_full(thread_id)
            nm = newest_message(thread)
            if nm:
                in_reply_to = header_value(nm["payload"], "Message-ID")
        except Exception:
            pass
        try:
            raw = build_raw(email, subject, body_text, None,
                            in_reply_to=in_reply_to)
            result = send_message(raw, thread_id=thread_id)
        except Exception as exc:
            log(f"follow-up send failed {email}: {exc}")
            continue

        new_mid = result.get("id")
        lead["lastMessageId"] = new_mid
        smi = lead.get("sent_message_ids", [])
        if new_mid and new_mid not in smi:
            smi.append(new_mid)
        lead["sent_message_ids"] = smi
        lead["followup_sent"] = True
        lead["updated"] = now_iso()
        log(f"sent 3-day follow-up to {email} (age {age_days:.1f}d)")
        sent += 1
        save_state(state)
    return sent


# ---------------------------------------------------------------------------
# Failure self-notify
# ---------------------------------------------------------------------------
def notify_failure(tb):
    date = datetime.now().strftime("%Y-%m-%d")
    short = tb.strip().splitlines()[-1][:120] if tb.strip() else "unknown"
    body = (
        "Der Golfausflug-Funnel-Loop ist mit einem unbehandelten Fehler "
        "abgebrochen.\n\n"
        "Traceback:\n" + tb + "\n\n"
        "Vorgeschlagener Fix: Pruefe zuletzt die gws-Auth (gws forms ...), das "
        "claude-CLI und state.json auf Beschaedigung. Danach python3 "
        "golfausflug-loop.py --dry-run laufen lassen.\n\n"
        "-- golfausflug-loop.py")
    try:
        tmp = os.path.join(SCRIPT_DIR, ".fail-notify.txt")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
        subprocess.run(
            ["bash", SEND_EMAIL_SH,
             f"[AI] Golfausflug-Loop FEHLER ({date}): {short}", tmp,
             "--allow-weekend"],
            capture_output=True, text=True)
    except Exception as exc:
        log(f"failure-notify itself failed: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    start = time.time()

    # a. KILL SWITCH
    if os.path.exists(PAUSE_FILE):
        append_run_log(0, 0, 0, time.time() - start, "paused")
        log("PAUSED-GOLFAUSFLUG present; exiting.")
        return 0

    # b. LOCK
    if not acquire_lock():
        return 0

    try:
        ensure_gws_on_path()
        kb = read_knowledge()
        state = load_state()
        migrate_state(state)  # backfill fields for pre-upgrade lead entries

        # c. POLL
        responses = poll_responses()
        log(f"polled {len(responses)} form response(s)")

        # d/e. new leads -> generate + send
        new_leads = process_new_leads(state, kb, responses)

        # f. reply rounds
        replies = process_reply_rounds(state, kb)

        # g. 3-day follow-up for leads who never replied
        followups = process_followups(state)

        save_state(state)
        dur = time.time() - start
        append_run_log(new_leads, replies, followups, dur, "ok")
        log(f"done: new_leads={new_leads} replies={replies} "
            f"followups={followups} in {dur:.1f}s")
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        tb = traceback.format_exc()
        log("UNHANDLED EXCEPTION:\n" + tb)
        release_lock()
        if not DRY_RUN:
            notify_failure(tb)
        sys.exit(1)
