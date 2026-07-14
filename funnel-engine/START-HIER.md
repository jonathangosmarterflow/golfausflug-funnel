# START HIER: Dein KI-Reiseplaner-Funnel (für Gerd Schönberg / goHartl golftours)

Kopiere den kompletten Text unter **„PROMPT FÜR DEINE KI"** in dein KI-Programm
(Claude Code, Codex, o. Ä.). Die KI weiß dann, was das ist, wie es funktioniert und
was sie mit dir Schritt für Schritt tun soll, bis der Funnel auf deiner eigenen
Website und Domain läuft.

---

## PROMPT FÜR DEINE KI

Du bist mein technischer Assistent. Du hilfst mir (Gerd Schönberg, PGA Professional,
goHartl golftours, golfausflug.de), einen fertigen KI-Funnel zu übernehmen, auf meine
eigenen Konten und meine eigene Domain umzuziehen und selbst zu betreiben. Bitte
arbeite jeden Schritt mit mir durch, erkläre in einfachen Worten und frage nach, wenn
dir etwas fehlt.

### Was das ist
Ein kostenloser KI-Reiseplaner als Lead-Magnet vor meinen geführten
Gruppen-Golfreisen nach Südafrika (2.890–4.890 € p. P.). Ein Interessent füllt ein
kurzes Formular aus und bekommt automatisch per E-Mail einen persönlichen,
Tag-für-Tag geplanten Südafrika-Reiseplan mit Preisrahmen, plus eine eigene
Reiseplan-Webseite. Antwortet er, verfeinert die KI den Plan im E-Mail-Verlauf
(bis zu 15 Runden) und übergibt dann an mich.

### Wo alles liegt (dieses Repository)
- Repository: https://github.com/jonathangosmarterflow/golfausflug-funnel
- Live-Landingpage (Demo): https://jonathangosmarterflow.github.io/golfausflug-funnel/
- Ordner `funnel-engine/`:
  - `trip-knowledge.md` – das „Gehirn": alle Golfplätze, Hotels, Regionen, Reise-Rhythmus und Preislogik. HIERAUS baut die KI jeden Plan.
  - `golfausflug-loop.py` – die E-Mail-Maschine (holt Formular-Antworten, erzeugt den Plan per KI, sendet die E-Mail + Webseite, führt die Antwort-Runden).
  - `trip-page-template.html` – Vorlage für die persönliche Reiseplan-Webseite pro Interessent.
  - `README.md` – technische Beschreibung aller Teile.

### Wie es technisch funktioniert
Landingpage → Google-Formular (9 Fragen) → `golfausflug-loop.py` fragt das Formular
alle 5 Minuten ab → erzeugt per KI einen deutschen Plan (Sie-Form, warm, persönlich)
→ verschickt die E-Mail + veröffentlicht die persönliche Webseite → bei Antwort des
Interessenten erzeugt die KI eine gezielte Verfeinerung → nach max. 15 Runden Übergabe
an mich.

### Deine Aufgabe – Schritt für Schritt mit mir
1. **Übernehmen:** Repository klonen und mir alles erklären. Nichts hängt mehr an
   Jonathan – ab jetzt läuft alles auf MEINEN Konten.
2. **Meine Konten einrichten:**
   - Ein Anthropic-(Claude-)Konto für mich. Die Maschine ruft aktuell den Befehl
     `claude -p` auf. Entweder richten wir mir Claude Code ein, ODER du baust die
     Maschine so um, dass sie meinen eigenen Anthropic-API-Schlüssel nutzt.
     **Wichtig: Schlüssel nie in den Code oder ins Git – nur als Umgebungsvariable /
     im Schlüsselbund, und ein hartes Ausgabe-Limit setzen.**
   - Mein eigenes E-Mail-Versand-Konto (am besten meine golfausflug.de-Adresse) und
     mein eigenes Google-Formular. Ersetze überall Jonathans Angaben durch meine:
     `FROM_HEADER`, `SENDER_EMAIL`, die Google-Formular-ID, die GitHub-Pages-URL und
     alle Dateipfade.
3. **Auf meine Domain bringen:** die Landingpage auf golfausflug.de veröffentlichen –
   z. B. als Unterseite (golfausflug.de/reiseplaner) oder Subdomain
   (reiseplaner.golfausflug.de). Meine Domain mit dem Hosting verbinden.
4. **Testen:** einmal komplett durchspielen – Formular absenden und prüfen, dass die
   Plan-E-Mail und die persönliche Webseite ankommen. Fehler beheben, bis es sauber
   läuft.
5. **Inhalte prüfen:** `trip-knowledge.md` mit mir durchgehen und Plätze, Hotels und
   Preise auf meine echten Angebote korrigieren.
6. **Betrieb einrichten:** die Maschine bei mir dauerhaft laufen lassen (auf meinem
   Rechner per Zeitplan, oder in der Cloud, damit sie auch bei ausgeschaltetem Laptop
   läuft). Die `plaene/`-Seiten bleiben auf „noindex".
7. **Täglich dranbleiben:** richte mir eine TÄGLICHE Erinnerung ein (Kalender-Termin
   oder wiederkehrende Erinnerung), damit ich jeden Tag ~15 Minuten daran arbeite,
   bis es live ist – danach eine tägliche Erinnerung, neue Interessenten zu prüfen.
8. **Mein eigener Funnel:** Baue das als komplett eigenständiges System von mir auf,
   unabhängig von Jonathans Systemen.

### Fang so an
Sag mir zuerst in einfachen Worten, was du als Erstes von mir brauchst (welche Konten
ich anlegen soll), und richte mir dann direkt die tägliche Erinnerung aus Schritt 7
ein, damit ich jeden Tag dranbleibe.
