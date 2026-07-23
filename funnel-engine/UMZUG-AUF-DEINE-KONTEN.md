# UMZUG: Alles auf Gerds eigene Konten (Anleitung für deine KI)

Stand: 23.07.2026. Dieses Dokument ist die komplette Anleitung, um die letzten Teile
des Funnels von Jonathans Konten auf Gerds eigene Konten umzuziehen. Kopiere es in
deine KI (Claude) oder lass sie diese Datei direkt aus dem Repository lesen und dann
Schritt für Schritt mit Gerd durcharbeiten.

---

## 1. Was aktuell noch wo liegt (der ehrliche Ist-Zustand)

**Auf Jonathans Seite läuft seit 14.07.2026 NICHTS mehr:**
- Die alte E-Mail-Maschine (`golfausflug-loop.py` auf Jonathans Laptop) ist seit dem
  14.07. abgeschaltet und bleibt aus. Sie verarbeitet nichts mehr.
- Es liegt KEIN Schlüssel (API-Key) von Jonathan in Gerds Repository oder dessen
  Secrets. Jonathan hat nie einen Anthropic-Key an das goooogolf-hub-Repo übergeben.

**Das EINZIGE, was noch auf Jonathans Konto liegt:**
- Das alte Google-Formular `Golfausflug Südafrika Reiseplan Leads`
  (ID `1dxA3uqRyML4LUSr3494HbKv6vDjHLgdUBj0Cid4lVkU`). Die Landingpage schickt
  Antworten dorthin, aber nur Jonathans Konto kann sie LESEN. Genau das ziehen wir um.
- Die Alt-Daten daraus (6 Einsendungen vom 11.07.2026) sind bereits als Google Sheet
  exportiert und für `goooogolf@googlemail.com` freigegeben:
  https://docs.google.com/spreadsheets/d/1ts2RTqc3DrdaFM9M9b5iEzxdAHN9T4Aw4HbbtEs0fSY/edit

**KI-Kosten:** Auf Jonathans Konto laufen keine KI-Kosten mehr. Prüfe im Repo
`goooogolf-hub` unter Settings → Secrets, welcher `ANTHROPIC_API_KEY` (o. ä.) dort
hinterlegt ist. Ist es ein Key aus Gerds eigenem Konto (console.anthropic.com,
angemeldet mit Gerds E-Mail), ist alles schon richtig. Falls unklar: neuen eigenen
Key anlegen (Schritt 4) und den alten im Secret ersetzen. Dann ist es zu 100 % Gerds.

---

## 2. Das Formular: exakte Feld-Spezifikation (13 Felder, exakt diese Reihenfolge)

Neues Google-Formular unter `goooogolf@googlemail.com` anlegen, Titel z. B.
`Golfausflug Südafrika Reiseplan Leads`. Alle Felder sind Kurzantwort-Textfelder:

| # | Feldname | Pflichtfeld |
|---|----------------|-------------|
| 1 | Vorname | JA |
| 2 | Nachname | nein |
| 3 | E-Mail | JA |
| 4 | Reisezeitraum | nein |
| 5 | Reisedauer | nein |
| 6 | Abflughafen | nein |
| 7 | Golf-Frequenz | nein |
| 8 | Interessen | nein |
| 9 | Reisebegleitung | nein |
| 10 | Mobilität | nein |
| 11 | Spielstärke | nein |
| 12 | Budget | nein |
| 13 | Anmerkungen | nein |

("Anmerkungen" ist das Feld "Besondere Wünsche" - der Name muss nur konsistent zu
eurem Code sein.)

**Die neuen `entry.XXXXXXX`-IDs herausfinden** (braucht ihr, falls die Landingpage
direkt an den `formResponse`-Endpunkt POSTet): im Formular oben auf die drei Punkte →
"Vorausgefüllten Link abrufen" → alle Felder mit Platzhaltern füllen → Link kopieren.
Im Link steht pro Feld `entry.1234567=...`. Diese IDs in der Landingpage (JS) und
überall im Code ersetzen, zusammen mit der neuen Formular-ID.

**Alternative (empfohlen, falls ihr sowieso schon einen Apps-Script-Endpoint habt):**
Das Google-Formular ganz weglassen und die Landingpage direkt an euren
Apps-Script-Endpoint POSTen lassen, der die Daten in ein Google SHEET unter Gerds
Konto schreibt. Ein Sheet ist einfacher zu lesen (für Mensch und KI), gehört komplett
Gerd, und ihr spart die Formular-Ebene. Beides ist okay - nehmt, was zu eurer
jetzigen Architektur passt.

---

## 3. Apps-Script-Endpoint unter Gerds Konto

1. script.google.com, angemeldet als `goooogolf@googlemail.com` → neues Projekt
   (oder euer bestehendes Script dorthin kopieren).
2. Bereitstellen → "Als Web-App bereitstellen": Ausführen als **ich**, Zugriff
   **jeder**. Die neue `https://script.google.com/macros/s/.../exec`-URL notieren.
3. Neues `FORM_TOKEN` erzeugen (zufällig, 32+ Zeichen, z. B. per
   `openssl rand -hex 24`). Ins Script eintragen UND als Secret im Repo
   `goooogolf-hub` hinterlegen (Settings → Secrets and variables → Actions).
   **Nie in den Code oder ins Git schreiben.**
4. In `funnel.yml` (GitHub Action) die Endpoint-URL auf die neue URL umstellen und
   das Secret referenzieren.

---

## 4. Eigener Anthropic-Key (falls noch nicht vorhanden)

1. console.anthropic.com → Konto mit Gerds E-Mail → API Keys → neuen Key erzeugen.
2. **Hartes Ausgabenlimit setzen** (Settings → Limits, z. B. 20-30 USD/Monat). Bei
   ~15 Leads/Monat kostet der Funnel realistisch nur wenige Euro; das Limit ist die
   Versicherung gegen Fehler-Schleifen.
3. Key als Secret `ANTHROPIC_API_KEY` im Repo hinterlegen, alten Wert ersetzen.
   Nie in Code, Chat oder Git.

---

## 5. Umstellung OHNE Ausfall (genau diese Reihenfolge)

Es gibt keinen Ausfall, weil die Landingpage bis zum Umschalt-Moment einfach weiter
an das alte Formular sendet:

1. Neues Formular (oder Sheet-Endpoint) + neuer Apps-Script-Endpoint + Secrets
   komplett fertig bauen und mit einem direkten Test-POST prüfen.
2. ERST DANN die Landingpage umstellen (Formular-ID + entry-IDs bzw. Endpoint-URL).
3. Kompletter End-zu-End-Test: Formular auf der echten Seite absenden → prüfen, dass
   die Plan-E-Mail UND die persönliche Reiseplan-Seite ankommen.
4. Gerd schreibt Jonathan kurz "läuft" → Jonathan schaltet das alte Formular am
   selben Tag auf "nimmt keine Antworten mehr an". Fertig - ab dann ist alles zu
   100 % auf Gerds Konten.

---

## 6. Cloud-Worker: so läuft die Maschine 24/7 ohne Laptop (Bauplan + Learnings)

Ihr habt mit GitHub Actions (`funnel.yml`) schon den richtigen Ansatz. So machen wir
es bei unserem eigenen Funnel, mit den Learnings aus dem Betrieb:

- **Zeitplan:** `on: schedule` mit Cron alle 10-15 Minuten reicht völlig (GitHub
  garantiert keine Minuten-Genauigkeit; für einen Lead-Funnel egal).
- **Doppel-Verarbeitung verhindern:** eine State-Datei (welche Lead-IDs/Antworten
  schon verarbeitet wurden) im Repo mitcommitten oder im Sheet als Status-Spalte
  führen. JEDER Lauf liest zuerst den State und überspringt Erledigtes. Zusätzlich
  in der Action `concurrency` setzen, damit nie zwei Läufe parallel laufen.
- **Harte Stopp-Grenzen:** max. 15 Antwort-Runden pro Lead (dann persönliche Übergabe
  an Gerd), plus das Ausgabenlimit im Anthropic-Konto. Eine KI-Schleife ohne
  Stopp-Bedingung ist ein Risiko.
- **Not-Aus:** ein Kill-Switch (z. B. eine Datei `PAUSED` im Repo oder eine
  Repo-Variable). Der Lauf prüft sie als Erstes und beendet sich sofort, wenn
  gesetzt. So kann Gerd die Maschine jederzeit mit einem Klick anhalten.
- **Fehler melden sich selbst:** wenn ein Lauf fehlschlägt, soll die Action eine
  kurze E-Mail an Gerd senden (oder mindestens: GitHub-Benachrichtigungen für
  fehlgeschlagene Workflows aktivieren). Gerd darf nie selbst nachschauen müssen,
  ob etwas kaputt ist - das System meldet sich.
- **Protokoll führen:** pro Lauf eine Zeile Log (Zeit, wie viele Leads verarbeitet,
  Ergebnis). Das macht Fehlersuche und Verbesserung einfach.
- **Reiseplan-Seiten:** unguessbare URL-Slugs, `noindex` im Head, Veröffentlichung
  darf das Versenden der E-Mail nie blockieren (erst E-Mail, Seite ist Bonus).
- **Qualität der Pläne:** die Wissensbasis (`trip-knowledge.md`) ist das Gehirn -
  Preise, Plätze und Hotels regelmäßig mit Gerd aktualisieren. Der Plan wird nur so
  gut wie diese Datei. Warme, persönliche Sie-Form, konkrete Tage, ehrlicher
  Preisrahmen.
- **Absender:** von einer echten golfausflug.de-Adresse senden (SPF/DKIM für die
  Domain einrichten), Antworten landen bei Gerd bzw. werden von der Maschine gelesen.

---

## 7. Was Jonathan weiterhin macht

- Nach eurem "läuft": altes Formular schließen (eine Minute, selber Tag).
- Bei Fragen jederzeit per E-Mail erreichbar. Dieses Repository bleibt online als
  gemeinsame Referenz; diese Datei ist der gemeinsame Projektstand.
