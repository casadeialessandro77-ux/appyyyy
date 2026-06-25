import streamlit as st
import datetime
import re
import io
import os
import json
import base64
import urllib.parse
import pandas as pd
import requests

# ── Librerie opzionali ──────────────────────────────────────────────────────
try:
    import pdfplumber
    PDF_OK = True
except ImportError:
    PDF_OK = False

# ── 1. IMPOSTAZIONI PAGINA & STATO ──────────────────────────────────────────
st.set_page_config(page_title="Pianificatore", page_icon="📅", layout="centered")

for chiave, default in [
    ("calendario_eventi", []),
    ("pagina", "inserimento"),
    ("suggerimenti_pendenti", []),
    ("settimana_offset", 0),
    ("gmail_token", None),
    ("ms_token", None),
]:
    if chiave not in st.session_state:
        st.session_state[chiave] = default

# ── 2. CONFIGURAZIONE OAUTH ──────────────────────────────────────────────────
TOKEN_DIR        = os.environ.get("TOKEN_DIR", "tokens")
GMAIL_CLIENT_ID  = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
MS_CLIENT_ID     = os.environ.get("MS_CLIENT_ID", "")
MS_TENANT_ID     = os.environ.get("MS_TENANT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
APP_URL          = os.environ.get("APP_URL", "http://localhost:8501")

GMAIL_REDIRECT   = APP_URL.rstrip("/") + "/"
MS_REDIRECT      = APP_URL.rstrip("/") + "/"

GMAIL_SCOPES     = "https://www.googleapis.com/auth/gmail.readonly"
MS_SCOPES        = "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Files.Read https://graph.microsoft.com/User.Read offline_access"

os.makedirs(TOKEN_DIR, exist_ok=True)

# ── 3. DIZIONARI ITALIANI ────────────────────────────────────────────────────
MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}
GIORNI_IT = {
    "lunedì": 0, "lunedi": 0, "lun": 0,
    "martedì": 1, "martedi": 1, "mar": 1,
    "mercoledì": 2, "mercoledi": 2, "mer": 2,
    "giovedì": 3, "giovedi": 3, "gio": 3,
    "venerdì": 4, "venerdi": 4, "ven": 4,
    "sabato": 5, "sab": 5,
    "domenica": 6, "dom": 6,
}
MESI_NOMI = {
    1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile",
    5: "Maggio", 6: "Giugno", 7: "Luglio", 8: "Agosto",
    9: "Settembre", 10: "Ottobre", 11: "Novembre", 12: "Dicembre",
}
GIORNI_NOMI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

# ── 4. TOKEN HELPERS ─────────────────────────────────────────────────────────
def salva_token(nome: str, dati: dict):
    path = os.path.join(TOKEN_DIR, f"{nome}_token.json")
    with open(path, "w") as f:
        json.dump(dati, f)

def carica_token(nome: str) -> dict | None:
    path = os.path.join(TOKEN_DIR, f"{nome}_token.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None

def elimina_token(nome: str):
    path = os.path.join(TOKEN_DIR, f"{nome}_token.json")
    if os.path.exists(path):
        os.remove(path)

# ── 5. GMAIL OAuth ────────────────────────────────────────────────────────────
def gmail_url_login() -> str:
    params = {
        "client_id": GMAIL_CLIENT_ID,
        "redirect_uri": GMAIL_REDIRECT,
        "response_type": "code",
        "scope": GMAIL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": "gmail",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

def gmail_scambia_codice(code: str) -> dict | None:
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "redirect_uri": GMAIL_REDIRECT,
        "grant_type": "authorization_code",
    })
    if r.ok:
        token = r.json()
        token["ottenuto_il"] = datetime.datetime.utcnow().isoformat()
        salva_token("gmail", token)
        return token
    return None

def gmail_refresh(token: dict) -> dict | None:
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": token.get("refresh_token"),
        "grant_type": "refresh_token",
    })
    if r.ok:
        nuovo = {**token, **r.json()}
        nuovo["ottenuto_il"] = datetime.datetime.utcnow().isoformat()
        salva_token("gmail", nuovo)
        return nuovo
    return None

def gmail_access_token() -> str | None:
    token = st.session_state.gmail_token or carica_token("gmail")
    if not token:
        return None
    # Controlla scadenza (margine 5 min)
    ottenuto = datetime.datetime.fromisoformat(token.get("ottenuto_il", "2000-01-01"))
    scadenza = ottenuto + datetime.timedelta(seconds=token.get("expires_in", 3600) - 300)
    if datetime.datetime.utcnow() > scadenza:
        token = gmail_refresh(token)
        if not token:
            return None
    st.session_state.gmail_token = token
    return token.get("access_token")

def gmail_leggi_allegati() -> list[str]:
    """Scarica allegati PDF/TXT dalle ultime 20 email e restituisce lista di testi."""
    access = gmail_access_token()
    if not access:
        return []
    headers = {"Authorization": f"Bearer {access}"}
    testi = []

    # Lista messaggi recenti
    r = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params={"maxResults": 20, "q": "has:attachment (filename:pdf OR filename:txt)"},
    )
    if not r.ok:
        return []

    messaggi = r.json().get("messages", [])
    for msg in messaggi[:10]:
        det = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
            headers=headers,
        ).json()

        oggetto = next(
            (h["value"] for h in det.get("payload", {}).get("headers", []) if h["name"] == "Subject"),
            "Senza oggetto"
        )

        def cerca_parti(parti):
            for parte in parti:
                if parte.get("parts"):
                    cerca_parti(parte["parts"])
                fname = parte.get("filename", "")
                body  = parte.get("body", {})
                att_id = body.get("attachmentId")
                if att_id and (fname.endswith(".pdf") or fname.endswith(".txt")):
                    att = requests.get(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}/attachments/{att_id}",
                        headers=headers,
                    ).json()
                    dati = base64.urlsafe_b64decode(att.get("data", "") + "==")
                    if fname.endswith(".txt"):
                        testi.append(("gmail", oggetto, dati.decode("utf-8", errors="ignore")))
                    elif fname.endswith(".pdf") and PDF_OK:
                        try:
                            with pdfplumber.open(io.BytesIO(dati)) as pdf:
                                testo = "\n".join(p.extract_text() or "" for p in pdf.pages)
                            testi.append(("gmail", oggetto, testo))
                        except Exception:
                            pass

        cerca_parti(det.get("payload", {}).get("parts", []))

    return testi

# ── 6. MICROSOFT OAuth ───────────────────────────────────────────────────────
def ms_url_login() -> str:
    params = {
        "client_id": MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": MS_REDIRECT,
        "scope": MS_SCOPES,
        "state": "microsoft",
        "response_mode": "query",
    }
    return f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/authorize?" + urllib.parse.urlencode(params)

def ms_scambia_codice(code: str) -> dict | None:
    r = requests.post(
        f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "code": code,
            "redirect_uri": MS_REDIRECT,
            "grant_type": "authorization_code",
            "scope": MS_SCOPES,
        },
    )
    if r.ok:
        token = r.json()
        token["ottenuto_il"] = datetime.datetime.utcnow().isoformat()
        salva_token("ms", token)
        return token
    return None

def ms_refresh(token: dict) -> dict | None:
    r = requests.post(
        f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "refresh_token": token.get("refresh_token"),
            "grant_type": "refresh_token",
            "scope": MS_SCOPES,
        },
    )
    if r.ok:
        nuovo = {**token, **r.json()}
        nuovo["ottenuto_il"] = datetime.datetime.utcnow().isoformat()
        salva_token("ms", nuovo)
        return nuovo
    return None

def ms_access_token() -> str | None:
    token = st.session_state.ms_token or carica_token("ms")
    if not token:
        return None
    ottenuto = datetime.datetime.fromisoformat(token.get("ottenuto_il", "2000-01-01"))
    scadenza = ottenuto + datetime.timedelta(seconds=token.get("expires_in", 3600) - 300)
    if datetime.datetime.utcnow() > scadenza:
        token = ms_refresh(token)
        if not token:
            return None
    st.session_state.ms_token = token
    return token.get("access_token")

def ms_leggi_allegati() -> list[tuple]:
    """Legge allegati PDF/TXT dalle ultime email in Outlook."""
    access = ms_access_token()
    if not access:
        return []
    headers = {"Authorization": f"Bearer {access}"}
    testi = []

    r = requests.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        headers=headers,
        params={
            "$top": 20,
            "$filter": "hasAttachments eq true",
            "$select": "id,subject",
        },
    )
    if not r.ok:
        return []

    for msg in r.json().get("value", [])[:10]:
        oggetto = msg.get("subject", "Senza oggetto")
        att_r = requests.get(
            f"https://graph.microsoft.com/v1.0/me/messages/{msg['id']}/attachments",
            headers=headers,
        )
        if not att_r.ok:
            continue
        for att in att_r.json().get("value", []):
            nome = att.get("name", "")
            if not (nome.endswith(".pdf") or nome.endswith(".txt")):
                continue
            dati = base64.b64decode(att.get("contentBytes", ""))
            if nome.endswith(".txt"):
                testi.append(("teams", oggetto, dati.decode("utf-8", errors="ignore")))
            elif nome.endswith(".pdf") and PDF_OK:
                try:
                    with pdfplumber.open(io.BytesIO(dati)) as pdf:
                        testo = "\n".join(p.extract_text() or "" for p in pdf.pages)
                    testi.append(("teams", oggetto, testo))
                except Exception:
                    pass
    return testi

# ── 7. PARSER ────────────────────────────────────────────────────────────────
def estrai_testo_txt(file) -> str:
    return file.read().decode("utf-8", errors="ignore")

def estrai_testo_pdf(file) -> str:
    if not PDF_OK:
        st.error("Installa pdfplumber: pip install pdfplumber")
        return ""
    testo = ""
    with pdfplumber.open(io.BytesIO(file.read())) as pdf:
        for p in pdf.pages:
            t = p.extract_text()
            if t:
                testo += t + "\n"
    return testo

def parse_data_italiana(testo_data: str):
    testo_data = testo_data.strip().lower()
    m = re.search(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})", testo_data)
    if m:
        g, me, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a < 100: a += 2000
        try: return datetime.date(a, me, g)
        except ValueError: pass
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MESI_IT.keys()) + r")\.?\s*(\d{2,4})?", testo_data)
    if m:
        g = int(m.group(1))
        me = MESI_IT[m.group(2)]
        a = int(m.group(3)) if m.group(3) else datetime.date.today().year
        if a < 100: a += 2000
        try: return datetime.date(a, me, g)
        except ValueError: pass
    return None

def parse_orario(testo: str):
    pattern = re.compile(
        r"(\d{1,2})[:\.](\d{2})\s*(?:-|–|alle|fino alle|a)\s*(\d{1,2})[:\.](\d{2})",
        re.IGNORECASE,
    )
    return [
        (f"{int(m.group(1)):02d}:{m.group(2)}", f"{int(m.group(3)):02d}:{m.group(4)}")
        for m in pattern.finditer(testo)
    ]

def parse_tabella_orario(testo: str) -> list[dict]:
    oggi = datetime.date.today()
    righe = [r.strip() for r in testo.splitlines() if r.strip()]
    d_inizio = d_fine = None
    pat = re.compile(r"dal\s+(\d{1,2}\s+\w+(?:\s+\d{2,4})?)\s+al\s+(\d{1,2}\s+\w+(?:\s+\d{2,4})?)", re.IGNORECASE)
    for riga in righe:
        m = pat.search(riga.lower())
        if m:
            d_inizio = parse_data_italiana(m.group(1))
            d_fine   = parse_data_italiana(m.group(2))
            break
    if not d_inizio or not d_fine:
        return []
    intestazione_idx = None
    fasce_orarie = []
    for i, riga in enumerate(righe):
        orari = parse_orario(riga)
        if len(orari) >= 2:
            intestazione_idx = i
            fasce_orarie = orari
            break
    if intestazione_idx is None:
        return []
    eventi = []
    for riga in righe[intestazione_idx + 1:]:
        riga_lower = riga.lower()
        giorno_num = giorno_nome = None
        for nome, num in GIORNI_IT.items():
            if riga_lower.startswith(nome):
                giorno_num, giorno_nome = num, nome
                break
        if giorno_num is None:
            continue
        resto = riga[len(giorno_nome):].strip()
        materie_riga = re.split(r"\s{2,}", resto)
        if len(materie_riga) < len(fasce_orarie):
            materie_riga = resto.split("\t") if "\t" in resto else re.split(r"\s{1,}", resto, maxsplit=len(fasce_orarie)-1)
        for i, (inizio_h, fine_h) in enumerate(fasce_orarie):
            if i >= len(materie_riga):
                break
            materia = materie_riga[i].strip().title()
            if not materia or materia.lower() in ("studio libero", "ripasso settimanale", "tutorato", "-", ""):
                continue
            corrente = d_inizio
            while corrente <= d_fine:
                if corrente.weekday() == giorno_num and corrente >= oggi:
                    eventi.append({"Data": corrente, "Materia": materia, "Inizio": inizio_h, "Fine": fine_h})
                corrente += datetime.timedelta(days=1)
    return eventi

def parse_programma(testo: str) -> list[dict]:
    oggi = datetime.date.today()
    eventi = parse_tabella_orario(testo)
    if eventi:
        return eventi
    testo_lower = testo.lower()
    pat = re.compile(
        r"(?P<materia>[A-Za-zÀ-ÿ ,'\-]{3,60?}?)\s+dal\s+"
        r"(?P<inizio>\d{1,2}\s+\w+(?:\s+\d{2,4})?)\s+(?:al|fino al|a)\s+"
        r"(?P<fine>\d{1,2}\s+\w+(?:\s+\d{2,4})?)",
        re.IGNORECASE,
    )
    for match in pat.finditer(testo_lower):
        materia  = match.group("materia").strip().title()
        d_inizio = parse_data_italiana(match.group("inizio"))
        d_fine   = parse_data_italiana(match.group("fine"))
        if not d_inizio or not d_fine:
            continue
        if d_fine < d_inizio:
            d_fine = d_fine.replace(year=d_fine.year + 1)
        contesto = testo_lower[max(0, match.start()-20):min(len(testo_lower), match.end()+300)]
        giorni_trovati = []
        for nome, num in GIORNI_IT.items():
            if re.search(r"\b" + re.escape(nome) + r"\b", contesto) and num not in giorni_trovati:
                giorni_trovati.append(num)
        if not giorni_trovati:
            giorni_trovati = [0, 1, 2, 3, 4]
        orari = parse_orario(contesto) or [("09:00", "11:00")]
        corrente = d_inizio
        while corrente <= d_fine:
            if corrente.weekday() in giorni_trovati and corrente >= oggi:
                idx = giorni_trovati.index(corrente.weekday())
                ih, fh = orari[idx % len(orari)]
                eventi.append({"Data": corrente, "Materia": materia or "Materia", "Inizio": ih, "Fine": fh})
            corrente += datetime.timedelta(days=1)
    if eventi:
        return eventi
    for riga in testo.splitlines():
        data = None
        for t in re.findall(r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{1,2}\s+\w+\s+\d{2,4}", riga):
            data = parse_data_italiana(t)
            if data: break
        if not data or data < oggi:
            continue
        for ih, fh in parse_orario(riga):
            eventi.append({"Data": data, "Materia": "Lezione", "Inizio": ih, "Fine": fh})
    return eventi

# ── 8. GESTIONE CALLBACK OAUTH ───────────────────────────────────────────────
params = st.query_params
if "code" in params and "state" in params:
    code  = params["code"]
    state = params["state"]
    st.query_params.clear()
    if state == "gmail":
        token = gmail_scambia_codice(code)
        if token:
            st.session_state.gmail_token = token
            st.session_state.pagina = "suggerimenti"
            st.success("Gmail collegato!")
    elif state == "microsoft":
        token = ms_scambia_codice(code)
        if token:
            st.session_state.ms_token = token
            st.session_state.pagina = "suggerimenti"
            st.success("Microsoft collegato!")

# ── 9. NAVBAR ────────────────────────────────────────────────────────────────
pagina = st.session_state.pagina

ICONE = {
    "inserimento":  '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><polyline points="9 15 12 12 15 15"/></svg>',
    "suggerimenti": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    "calendario":   '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
    "vuota1": '<svg viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
    "vuota2": '<svg viewBox="0 0 24 24"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    "vuota3": '<svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
}
LABEL_ICONE = {
    "inserimento":  "Inserisci",
    "suggerimenti": "Suggerimenti",
    "calendario":   "Calendario",
    "vuota1":       "Avvisi",
    "vuota2":       "Statistiche",
    "vuota3":       "Profilo",
}
CLICCABILI = ["inserimento", "suggerimenti", "calendario"]

# ── CSS globale + navbar decorativa ─────────────────────────────────────────
items_html = ""
for key, svg in ICONE.items():
    attivo  = "active" if pagina == key else ""
    opacita = "" if key in CLICCABILI else "opacity:0.38;"
    items_html += (
        f"<div class='nav-item {attivo}' style='{opacita}'>"
        f"<span class='nav-icon'>{svg}</span>"
        f"<span class='nav-label'>{LABEL_ICONE[key]}</span>"
        f"</div>"
    )

st.markdown(f"""
<style>
[data-testid="stSidebar"] {{ display: none; }}
[data-testid="collapsedControl"] {{ display: none; }}
.main .block-container {{ padding-bottom: 90px !important; }}

/* ── Navbar decorativa ── */
.bottom-nav {{
    position: fixed; bottom: 0; left: 0; right: 0;
    height: 64px; background: #e8eaf0;
    border-top: 1px solid #cfd3de;
    display: flex; align-items: center; justify-content: center;
    z-index: 100; box-shadow: 0 -2px 14px rgba(0,0,0,0.09);
    pointer-events: none;
}}
.nav-item {{
    flex: 1; max-width: 90px;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    gap: 3px; padding: 6px 0; border-radius: 12px;
    user-select: none;
}}
.nav-icon svg {{
    width: 22px; height: 22px; fill: none;
    stroke: #7a8099; stroke-width: 1.7;
    stroke-linecap: round; stroke-linejoin: round;
}}
.nav-item.active .nav-icon svg {{ stroke: #1a1a2e; }}
.nav-label {{
    font-size: 0.58rem; color: #7a8099;
    letter-spacing: 0.04em; font-family: sans-serif;
    font-weight: 500; text-transform: uppercase;
}}
.nav-item.active .nav-label {{ color: #1a1a2e; font-weight: 700; }}

/* ── Pulsanti Streamlit sovrapposti alla navbar ── */
/* Contenitore colonne nav */
div[data-testid="stHorizontalBlock"].nav-row {{
    position: fixed !important;
    bottom: 0 !important;
    left: 0 !important;
    right: 0 !important;
    height: 64px !important;
    z-index: 200 !important;
    display: flex !important;
    gap: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    background: transparent !important;
}}
/* Ogni colonna occupa 1/6 della navbar */
div[data-testid="stHorizontalBlock"].nav-row > div[data-testid="stColumn"] {{
    flex: 1 !important;
    padding: 0 !important;
    min-width: 0 !important;
}}
/* Il pulsante riempie tutta la cella ed è trasparente */
div[data-testid="stHorizontalBlock"].nav-row button {{
    width: 100% !important;
    height: 64px !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: transparent !important;
    font-size: 0 !important;
    cursor: pointer !important;
    border-radius: 0 !important;
    padding: 0 !important;
}}
div[data-testid="stHorizontalBlock"].nav-row button:hover {{
    background: rgba(0,0,0,0.05) !important;
}}
</style>
<div class="bottom-nav">{items_html}</div>
""", unsafe_allow_html=True)

# ── Pulsanti reali sovrapposti — usiamo un div wrapper con classe nav-row ──
st.markdown('<div class="nav-row" data-testid="stHorizontalBlock">', unsafe_allow_html=True)
_c = st.columns(6)
with _c[0]:
    if st.button("I", key="nav_inserimento"):
        st.session_state.pagina = "inserimento"; st.rerun()
with _c[1]:
    if st.button("S", key="nav_suggerimenti"):
        st.session_state.pagina = "suggerimenti"; st.rerun()
with _c[2]:
    if st.button("C", key="nav_calendario"):
        st.session_state.pagina = "calendario"; st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# ── PAGINA 1: INSERIMENTO ────────────────────────────────────────────────────
if pagina == "inserimento":
    st.title("Inserimento Programmi")
    st.write("Carica un file **PDF** o **TXT**, oppure incolla il testo del programma.")

    testo_manuale = st.text_area(
        "Testo del programma:",
        placeholder="Es. 'Corso di Storia dal 15 Giugno al 17 Settembre, Lunedì e Mercoledì dalle 9:00 alle 11:00'",
        height=150,
    )
    uploaded_file = st.file_uploader("Oppure carica un file", type=["txt", "pdf"])

    testo_file = ""
    if uploaded_file:
        if uploaded_file.type == "application/pdf":
            testo_file = estrai_testo_pdf(uploaded_file)
        else:
            testo_file = estrai_testo_txt(uploaded_file)
        with st.expander("📄 Testo estratto dal file"):
            st.text(testo_file[:3000] + ("..." if len(testo_file) > 3000 else ""))

    if st.button("✨ Genera Calendario"):
        testo = testo_file if testo_file else testo_manuale
        if not testo.strip():
            st.warning("Inserisci del testo o carica un file prima di procedere.")
        else:
            with st.spinner("Analisi in corso..."):
                nuovi = parse_programma(testo)
            if nuovi:
                st.session_state.calendario_eventi.extend(nuovi)
                st.success(f"✅ Generati **{len(nuovi)} eventi** futuri.")
            else:
                st.error("⚠️ Non ho trovato date/orari riconoscibili nel testo.")

# ── PAGINA 2: SUGGERIMENTI (Gmail + Teams) ───────────────────────────────────
elif pagina == "suggerimenti":
    st.title("Suggerimenti Automatici")
    st.write("Collega Gmail e/o Microsoft per leggere automaticamente allegati con programmi e orari.")

    # ── Connessione servizi ──────────────────────────────────────────────────
    col_g, col_m = st.columns(2)

    with col_g:
        st.markdown("#### Gmail")
        gmail_ok = gmail_access_token() is not None
        if gmail_ok:
            st.success("✅ Connesso")
            if st.button("Disconnetti Gmail"):
                elimina_token("gmail")
                st.session_state.gmail_token = None
                st.rerun()
        else:
            if GMAIL_CLIENT_ID:
                st.markdown(f"[🔗 Collega Gmail]({gmail_url_login()})", unsafe_allow_html=False)
            else:
                st.warning("Variabili GMAIL_* non configurate su Render.")

    with col_m:
        st.markdown("#### Microsoft / Teams")
        ms_ok = ms_access_token() is not None
        if ms_ok:
            st.success("✅ Connesso")
            if st.button("Disconnetti Microsoft"):
                elimina_token("ms")
                st.session_state.ms_token = None
                st.rerun()
        else:
            if MS_CLIENT_ID:
                st.markdown(f"[🔗 Collega Microsoft]({ms_url_login()})", unsafe_allow_html=False)
            else:
                st.warning("Variabili MS_* non configurate su Render.")

    st.divider()

    # ── Scansione ────────────────────────────────────────────────────────────
    if st.button("🔍 Scansiona email alla ricerca di programmi"):
        testi_trovati = []
        with st.spinner("Lettura Gmail..."):
            if gmail_ok:
                testi_trovati.extend(gmail_leggi_allegati())
        with st.spinner("Lettura Microsoft..."):
            if ms_ok:
                testi_trovati.extend(ms_leggi_allegati())

        if not testi_trovati:
            st.info("Nessun allegato PDF o TXT trovato nelle ultime email.")
        else:
            nuovi_suggerimenti = []
            for origine, oggetto, testo in testi_trovati:
                eventi = parse_programma(testo)
                if eventi:
                    nuovi_suggerimenti.append({
                        "origine": origine,
                        "oggetto": oggetto,
                        "eventi": eventi,
                        "testo_preview": testo[:400],
                    })
            if nuovi_suggerimenti:
                # Evita duplicati già presenti
                esistenti = {
                    (e["Data"], e["Materia"], e["Inizio"])
                    for e in st.session_state.calendario_eventi
                }
                for s in nuovi_suggerimenti:
                    s["eventi"] = [
                        e for e in s["eventi"]
                        if (e["Data"], e["Materia"], e["Inizio"]) not in esistenti
                    ]
                nuovi_suggerimenti = [s for s in nuovi_suggerimenti if s["eventi"]]
                st.session_state.suggerimenti_pendenti = nuovi_suggerimenti
                if nuovi_suggerimenti:
                    st.success(f"Trovati **{len(nuovi_suggerimenti)} programmi** con eventi nuovi!")
                else:
                    st.info("Tutti gli eventi trovati sono già nel calendario.")
            else:
                st.info("Allegati trovati ma nessun programma riconoscibile.")

    # ── Lista suggerimenti in attesa ─────────────────────────────────────────
    if st.session_state.suggerimenti_pendenti:
        st.markdown("### Programmi trovati — conferma o rifiuta")

        da_rimuovere = []
        for idx, sug in enumerate(st.session_state.suggerimenti_pendenti):
            icona = "📧" if sug["origine"] == "gmail" else "💼"
            with st.container():
                st.markdown(
                    f"<div style='background:#f7f8fc;border:1.5px solid #e2e6f0;"
                    f"border-radius:12px;padding:14px 16px;margin-bottom:12px;'>"
                    f"<div style='font-size:0.8rem;color:#888;margin-bottom:4px;'>"
                    f"{icona} {'Gmail' if sug['origine']=='gmail' else 'Microsoft'}</div>"
                    f"<div style='font-weight:700;font-size:1rem;margin-bottom:8px;'>{sug['oggetto']}</div>"
                    f"<div style='font-size:0.78rem;color:#555;font-family:monospace;"
                    f"background:#eef0f6;border-radius:6px;padding:8px;margin-bottom:10px;'>"
                    f"{sug['testo_preview'].replace(chr(10),'<br>')}...</div>"
                    f"<div style='font-size:0.82rem;color:#333;'>"
                    f"<b>{len(sug['eventi'])} eventi trovati</b> · "
                    f"dal {sug['eventi'][0]['Data'].strftime('%d/%m/%Y')} "
                    f"al {sug['eventi'][-1]['Data'].strftime('%d/%m/%Y')}"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )

                # Anteprima primi 5 eventi
                with st.expander(f"Anteprima eventi ({len(sug['eventi'])} totali)"):
                    for ev in sug["eventi"][:5]:
                        st.markdown(
                            f"📅 **{ev['Data'].strftime('%d/%m/%Y')}** — "
                            f"{ev['Materia']} · {ev['Inizio']}–{ev['Fine']}"
                        )
                    if len(sug["eventi"]) > 5:
                        st.markdown(f"*...e altri {len(sug['eventi'])-5} eventi*")

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Aggiungi al calendario", key=f"acc_{idx}"):
                        st.session_state.calendario_eventi.extend(sug["eventi"])
                        da_rimuovere.append(idx)
                        st.success(f"Aggiunti {len(sug['eventi'])} eventi!")
                with c2:
                    if st.button("❌ Ignora", key=f"ign_{idx}"):
                        da_rimuovere.append(idx)

        for i in sorted(da_rimuovere, reverse=True):
            st.session_state.suggerimenti_pendenti.pop(i)
        if da_rimuovere:
            st.rerun()
    else:
        if gmail_ok or ms_ok:
            st.info("Nessun suggerimento in attesa. Clicca **Scansiona** per cercare nuovi programmi.")

# ── PAGINA 3: CALENDARIO ─────────────────────────────────────────────────────
elif pagina == "calendario":
    PALETTE = ["#4F86C6","#E07B54","#5BAD8F","#A66CC9","#D4A843","#C95B7A","#4AADB5","#7B8FA1"]

    st.markdown("""
    <style>
    .settimana-header { text-align:center; font-size:1.6rem; font-weight:700; color:#1a1a2e; margin-bottom:0.2rem; }
    .mese-label { text-align:center; font-size:0.95rem; color:#555; margin-bottom:1.2rem; text-transform:uppercase; letter-spacing:.08em; }
    </style>""", unsafe_allow_html=True)

    col_titolo, col_svuota = st.columns([5, 1])
    with col_titolo:
        st.title("Il tuo Calendario")
    with col_svuota:
        st.write("")
        if st.button("🗑️ Svuota", use_container_width=True):
            st.session_state.calendario_eventi = []
            st.rerun()

    if not st.session_state.calendario_eventi:
        st.warning("Il calendario è vuoto. Vai alla pagina di inserimento per generare gli eventi.")
    else:
        df = pd.DataFrame(st.session_state.calendario_eventi)
        df = df.sort_values(by=["Data", "Inizio"]).reset_index(drop=True)

        prima_data = df["Data"].min()
        lunedi_base = prima_data - datetime.timedelta(days=prima_data.weekday())
        lunedi_corrente = lunedi_base + datetime.timedelta(weeks=st.session_state.settimana_offset)
        domenica_corrente = lunedi_corrente + datetime.timedelta(days=6)
        ultima_data = df["Data"].max()
        lunedi_ultima = ultima_data - datetime.timedelta(days=ultima_data.weekday())
        n_settimane = int((lunedi_ultima - lunedi_base).days / 7) + 1

        col_prec, col_info, col_succ = st.columns([1, 4, 1])
        with col_prec:
            if st.button("◀", use_container_width=True, disabled=(st.session_state.settimana_offset <= 0)):
                st.session_state.settimana_offset -= 1; st.rerun()
        with col_info:
            if lunedi_corrente.month == domenica_corrente.month:
                label_mese = f"{MESI_NOMI[lunedi_corrente.month]} {lunedi_corrente.year}"
            else:
                label_mese = f"{MESI_NOMI[lunedi_corrente.month]} – {MESI_NOMI[domenica_corrente.month]} {domenica_corrente.year}"
            st.markdown(f"<div class='settimana-header'>{label_mese}</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='mese-label'>Settimana {st.session_state.settimana_offset+1} di {n_settimane} &nbsp;·&nbsp; "
                f"{lunedi_corrente.strftime('%d/%m')} – {domenica_corrente.strftime('%d/%m/%Y')}</div>",
                unsafe_allow_html=True,
            )
        with col_succ:
            if st.button("▶", use_container_width=True, disabled=(st.session_state.settimana_offset >= n_settimane - 1)):
                st.session_state.settimana_offset += 1; st.rerun()

        tutte_materie = sorted(df["Materia"].unique())
        colori_materia = {m: PALETTE[i % len(PALETTE)] for i, m in enumerate(tutte_materie)}

        with st.expander("🔍 Filtra materie", expanded=False):
            filtro_materie = st.multiselect("Mostra:", options=tutte_materie, default=list(tutte_materie), label_visibility="collapsed")

        mask = (df["Data"] >= lunedi_corrente) & (df["Data"] <= domenica_corrente) & (df["Materia"].isin(filtro_materie))
        df_settimana = df[mask]

        oggi = datetime.date.today()
        giorni_settimana = [lunedi_corrente + datetime.timedelta(days=i) for i in range(7)]
        fasce_settimana = sorted(
            df_settimana[["Inizio","Fine"]].drop_duplicates().apply(lambda r:(r["Inizio"],r["Fine"]),axis=1).tolist()
        ) if not df_settimana.empty else []

        CARD_H = 72
        html = """<style>
        .cal-table{width:100%;border-collapse:separate;border-spacing:4px 0;table-layout:fixed;}
        .cal-th{background:#1a1a2e;color:white;border-radius:10px 10px 0 0;padding:8px 4px 6px;text-align:center;font-size:.78rem;}
        .cal-th.oggi{background:#4F86C6;}
        .cal-num{font-size:1.45rem;font-weight:800;line-height:1.1;}
        .cal-dn{font-size:.68rem;opacity:.85;text-transform:uppercase;letter-spacing:.05em;}
        .cal-td{background:#f7f8fc;border-left:1.5px solid #e2e6f0;border-right:1.5px solid #e2e6f0;padding:4px;vertical-align:top;width:14.28%;}
        .cal-td-bottom{background:#f7f8fc;border-left:1.5px solid #e2e6f0;border-right:1.5px solid #e2e6f0;border-bottom:1.5px solid #e2e6f0;border-radius:0 0 10px 10px;height:12px;}
        .ev{border-radius:7px;padding:6px 8px;color:white;font-size:.74rem;line-height:1.35;height:""" + str(CARD_H) + """px;box-sizing:border-box;overflow:hidden;display:flex;flex-direction:column;justify-content:center;}
        .ev-titolo{font-weight:700;font-size:.76rem;}
        .ev-orario{opacity:.88;font-size:.68rem;margin-top:2px;}
        .ev-vuoto{height:""" + str(CARD_H) + """px;background:#eef0f6;border-radius:7px;border:1.5px dashed #d0d4e8;}
        .fascia-label{font-size:.65rem;color:#888;text-align:right;padding-right:6px;white-space:nowrap;vertical-align:middle;width:52px;}
        </style><table class="cal-table"><thead><tr><td style="width:52px"></td>"""

        for g in giorni_settimana:
            cls = "oggi" if g == oggi else ""
            html += f"<th class='cal-th {cls}'><div class='cal-num'>{g.day}</div><div class='cal-dn'>{GIORNI_NOMI[g.weekday()][:3]}</div></th>"
        html += "</tr></thead><tbody>"

        if not fasce_settimana:
            html += "<tr><td class='fascia-label'></td>"
            for _ in giorni_settimana:
                html += "<td class='cal-td cal-td-bottom' style='height:80px;text-align:center;color:#aab;font-size:.75rem;padding-top:20px;'>—</td>"
            html += "</tr>"
        else:
            for fi, (ih, fh) in enumerate(fasce_settimana):
                is_ultima = fi == len(fasce_settimana) - 1
                td_cls = "cal-td" + (" cal-td-bottom" if is_ultima else "")
                html += f"<tr><td class='fascia-label'>{ih}<br><span style='color:#bbb'>→</span><br>{fh}</td>"
                for g in giorni_settimana:
                    ev_c = df_settimana[(df_settimana["Data"]==g)&(df_settimana["Inizio"]==ih)&(df_settimana["Fine"]==fh)]
                    if ev_c.empty:
                        html += f"<td class='{td_cls}'><div class='ev-vuoto'></div></td>"
                    else:
                        ev = ev_c.iloc[0]
                        c = colori_materia.get(ev["Materia"],"#4F86C6")
                        html += f"<td class='{td_cls}'><div class='ev' style='background:{c};'><div class='ev-titolo'>{ev['Materia']}</div><div class='ev-orario'>🕐 {ih} – {fh}</div></div></td>"
                html += "</tr>"
            if not is_ultima:
                html += "<tr><td></td>" + "".join(f"<td class='cal-td-bottom'></td>" for _ in giorni_settimana) + "</tr>"

        html += "</tbody></table>"
        st.markdown(html, unsafe_allow_html=True)

        if not df_settimana.empty:
            st.divider()
            st.markdown("**Rimuovi un evento:**")
            for ih, fh in fasce_settimana:
                for g in giorni_settimana:
                    ev_c = df_settimana[(df_settimana["Data"]==g)&(df_settimana["Inizio"]==ih)&(df_settimana["Fine"]==fh)]
                    if not ev_c.empty:
                        ev = ev_c.iloc[0]
                        ri = df[(df["Data"]==ev["Data"])&(df["Materia"]==ev["Materia"])&(df["Inizio"]==ev["Inizio"])].index
                        if len(ri) > 0:
                            colore = colori_materia.get(ev["Materia"],"#4F86C6")
                            c1, c2 = st.columns([5,1])
                            with c1:
                                st.markdown(
                                    f"<div style='display:flex;align-items:center;gap:8px;padding:3px 0;'>"
                                    f"<div style='width:10px;height:10px;border-radius:3px;background:{colore};flex-shrink:0;'></div>"
                                    f"<span style='font-size:.82rem;'><b>{g.strftime('%a %d/%m')}</b> · {ev['Materia']} · {ih}–{fh}</span></div>",
                                    unsafe_allow_html=True,
                                )
                            with c2:
                                if st.button("✕", key=f"del_{ri[0]}", help="Rimuovi"):
                                    st.session_state.calendario_eventi.pop(ri[0]); st.rerun()

        st.divider()
        st.markdown("**Legenda materie**")
        leg_cols = st.columns(min(len(tutte_materie), 4))
        for i, mat in enumerate(tutte_materie):
            with leg_cols[i % len(leg_cols)]:
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:7px;margin-bottom:4px;'>"
                    f"<div style='width:14px;height:14px;border-radius:4px;background:{colori_materia[mat]};flex-shrink:0;'></div>"
                    f"<span style='font-size:.82rem;'>{mat}</span></div>",
                    unsafe_allow_html=True,
                )
