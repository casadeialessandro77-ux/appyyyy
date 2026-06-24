import streamlit as st
import datetime
import re
import io
import pandas as pd

# ── Librerie opzionali ──────────────────────────────────────────────────────
try:
    import pdfplumber
    PDF_OK = True
except ImportError:
    PDF_OK = False

# ── 1. IMPOSTAZIONI PAGINA & STATO ──────────────────────────────────────────
st.set_page_config(page_title="Pianificatore", page_icon="📅", layout="centered")

if "calendario_eventi" not in st.session_state:
    st.session_state.calendario_eventi = []

# ── 2. DIZIONARI ITALIANI ────────────────────────────────────────────────────
MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    # abbreviazioni
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

# ── 3. FUNZIONI DI ESTRAZIONE TESTO ─────────────────────────────────────────
def estrai_testo_txt(file) -> str:
    return file.read().decode("utf-8", errors="ignore")

def estrai_testo_pdf(file) -> str:
    if not PDF_OK:
        st.error("Libreria 'pdfplumber' non installata. Esegui: pip install pdfplumber")
        return ""
    testo = ""
    with pdfplumber.open(io.BytesIO(file.read())) as pdf:
        for pagina in pdf.pages:
            t = pagina.extract_text()
            if t:
                testo += t + "\n"
    return testo

# ── 4. PARSER PRINCIPALE ─────────────────────────────────────────────────────
def parse_data_italiana(testo_data: str) -> datetime.date | None:
    """
    Converte stringhe tipo:
      '15 giugno 2026', '15/06/2026', '15-06-2026', '15.06.2026'
    in un oggetto datetime.date.
    """
    testo_data = testo_data.strip().lower()

    # Formato numerico: 15/06/2026  o  15-06-2026  o  15.06.2026
    m = re.search(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})", testo_data)
    if m:
        g, me, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a < 100:
            a += 2000
        try:
            return datetime.date(a, me, g)
        except ValueError:
            pass

    # Formato testuale: 15 giugno 2026
    m = re.search(
        r"(\d{1,2})\s+(" + "|".join(MESI_IT.keys()) + r")\.?\s*(\d{2,4})?",
        testo_data,
    )
    if m:
        g = int(m.group(1))
        me = MESI_IT[m.group(2)]
        a = int(m.group(3)) if m.group(3) else datetime.date.today().year
        if a < 100:
            a += 2000
        try:
            return datetime.date(a, me, g)
        except ValueError:
            pass

    return None


def parse_orario(testo: str):
    """
    Estrae coppie (inizio, fine) tipo '09:00 - 11:00' oppure '9:00 alle 11:00'.
    Restituisce lista di tuple ("09:00", "11:00").
    """
    pattern = re.compile(
        r"(\d{1,2})[:\.](\d{2})\s*(?:-|–|alle|fino alle|a)\s*(\d{1,2})[:\.](\d{2})",
        re.IGNORECASE,
    )
    risultati = []
    for m in pattern.finditer(testo):
        inizio = f"{int(m.group(1)):02d}:{m.group(2)}"
        fine   = f"{int(m.group(3)):02d}:{m.group(4)}"
        risultati.append((inizio, fine))
    return risultati


def parse_tabella_orario(testo: str) -> list[dict]:
    """
    Riconosce il formato tabella settimanale tipo:
      Giorno  08:30-10:00  10:15-11:45  ...
      Lunedì  Analisi Mat  Fisica I     ...
      ...
      Periodo di riferimento: dal 26 giugno 2026 al 17 settembre 2026

    Restituisce eventi per ogni combinazione giorno+fascia oraria+materia,
    espansi su tutte le settimane del periodo, escludendo date passate.
    """
    oggi = datetime.date.today()
    righe = [r.strip() for r in testo.splitlines() if r.strip()]

    # 1) Trova il periodo dal testo (es. "dal 26 giugno 2026 al 17 settembre 2026")
    d_inizio, d_fine = None, None
    pattern_periodo = re.compile(
        r"dal\s+(\d{1,2}\s+\w+(?:\s+\d{2,4})?)\s+al\s+(\d{1,2}\s+\w+(?:\s+\d{2,4})?)",
        re.IGNORECASE,
    )
    for riga in righe:
        m = pattern_periodo.search(riga.lower())
        if m:
            d_inizio = parse_data_italiana(m.group(1))
            d_fine   = parse_data_italiana(m.group(2))
            break

    if not d_inizio or not d_fine:
        return []  # senza periodo non possiamo espandere

    # 2) Trova la riga di intestazione con gli orari
    #    Es: "Giorno 08:30-10:00 10:15-11:45 13:00-14:30 14:45-16:15"
    pattern_orario = re.compile(r"\d{1,2}[:\.]?\d{2}\s*[-–]\s*\d{1,2}[:\.]?\d{2}")
    intestazione_idx = None
    fasce_orarie = []  # lista di tuple ("08:30", "10:00")

    for i, riga in enumerate(righe):
        orari_trovati = parse_orario(riga)
        if len(orari_trovati) >= 2:  # almeno 2 fasce nella stessa riga = intestazione
            intestazione_idx = i
            fasce_orarie = orari_trovati
            break

    if intestazione_idx is None or not fasce_orarie:
        return []

    # 3) Leggi le righe successive: ogni riga che inizia con un giorno è una riga dati
    #    Es: "Lunedì Analisi Matematica Fisica I Informatica Studio Libero"
    #    Strategia: split per trovare il giorno, poi le materie per posizione
    eventi = []
    nomi_giorni_lista = list(GIORNI_IT.keys())

    for riga in righe[intestazione_idx + 1:]:
        riga_lower = riga.lower()

        # Cerca se la riga inizia con un nome giorno
        giorno_num = None
        giorno_nome = None
        for nome, num in GIORNI_IT.items():
            if riga_lower.startswith(nome):
                giorno_num  = num
                giorno_nome = nome
                break

        if giorno_num is None:
            continue  # riga non è un giorno della settimana

        # Rimuovi il nome del giorno dall'inizio e split il resto in materie
        resto = riga[len(giorno_nome):].strip()

        # Le materie sono separate da 2+ spazi (layout a colonne del PDF)
        # Proviamo prima con doppio spazio, poi con spazio singolo come fallback
        materie_riga = re.split(r"\s{2,}", resto)
        if len(materie_riga) < len(fasce_orarie):
            # Alcuni PDF usano tab o spazio singolo
            materie_riga = resto.split("\t") if "\t" in resto else re.split(r"\s{1,}", resto, maxsplit=len(fasce_orarie)-1)

        # Associa ogni fascia oraria alla materia corrispondente
        for i, (inizio_h, fine_h) in enumerate(fasce_orarie):
            if i >= len(materie_riga):
                break
            materia = materie_riga[i].strip().title()
            if not materia or materia.lower() in ("studio libero", "ripasso settimanale", "tutorato", "-", ""):
                continue  # salta slot non didattici

            # Espandi su tutte le settimane del periodo
            corrente = d_inizio
            while corrente <= d_fine:
                if corrente.weekday() == giorno_num and corrente >= oggi:
                    eventi.append({
                        "Data":    corrente,
                        "Materia": materia,
                        "Inizio":  inizio_h,
                        "Fine":    fine_h,
                    })
                corrente += datetime.timedelta(days=1)

    return eventi


def parse_programma(testo: str) -> list[dict]:
    """
    Analizza il testo completo e restituisce una lista di eventi da aggiungere
    al calendario, escludendo date già passate.
    """
    oggi = datetime.date.today()
    testo_lower = testo.lower()
    eventi = []

    # ── 0) Prova prima il formato tabella settimanale ────────────────────────
    eventi_tabella = parse_tabella_orario(testo)
    if eventi_tabella:
        return eventi_tabella

    # ── A) Cerca blocchi "materia ... dal ... al ..." ────────────────────────
    # Pattern: "Corso di X dal 15 giugno al 17 settembre, lunedì e mercoledì dalle 9:00 alle 11:00"
    pattern_blocco = re.compile(
        r"(?P<materia>[A-Za-zÀ-ÿ ,'\-]{3,60?}?)"   # nome materia (pigro)
        r"\s+dal\s+"
        r"(?P<inizio>\d{1,2}\s+\w+(?:\s+\d{2,4})?)"  # data inizio
        r"\s+(?:al|fino al|a)\s+"
        r"(?P<fine>\d{1,2}\s+\w+(?:\s+\d{2,4})?)",   # data fine
        re.IGNORECASE,
    )

    for match in pattern_blocco.finditer(testo_lower):
        materia  = match.group("materia").strip().title()
        d_inizio = parse_data_italiana(match.group("inizio"))
        d_fine   = parse_data_italiana(match.group("fine"))

        if not d_inizio or not d_fine:
            continue

        # Se l'anno non era specificato, prova anno corrente / successivo
        if d_fine < d_inizio:
            d_fine = d_fine.replace(year=d_fine.year + 1)

        # Estrai giorni della settimana dalla stessa riga/frase
        inizio_pos = max(0, match.start() - 20)
        fine_pos   = min(len(testo_lower), match.end() + 300)
        contesto   = testo_lower[inizio_pos:fine_pos]

        giorni_trovati = []
        for nome_giorno, num in GIORNI_IT.items():
            if re.search(r"\b" + re.escape(nome_giorno) + r"\b", contesto):
                if num not in giorni_trovati:
                    giorni_trovati.append(num)

        if not giorni_trovati:
            # Nessun giorno specificato → tutti i giorni feriali
            giorni_trovati = [0, 1, 2, 3, 4]

        # Estrai orari dalla stessa zona di testo
        orari = parse_orario(contesto)
        if not orari:
            orari = [("09:00", "11:00")]  # fallback generico

        # Genera gli eventi giorno per giorno
        corrente = d_inizio
        while corrente <= d_fine:
            if corrente.weekday() in giorni_trovati and corrente >= oggi:
                # Assegna l'orario: se ci sono più orari, li cicla sui giorni
                idx_giorno = giorni_trovati.index(corrente.weekday())
                inizio_h, fine_h = orari[idx_giorno % len(orari)]
                eventi.append({
                    "Data":    corrente,
                    "Materia": materia if materia else "Materia non specificata",
                    "Inizio":  inizio_h,
                    "Fine":    fine_h,
                })
            corrente += datetime.timedelta(days=1)

    # ── B) Fallback: cerca righe con data + orario senza struttura "dal...al" ─
    if not eventi:
        righe = testo.splitlines()
        for riga in righe:
            data = None
            # cerca data numerica o testuale nella riga
            for tentativo in re.findall(
                r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{1,2}\s+\w+\s+\d{2,4}", riga
            ):
                data = parse_data_italiana(tentativo)
                if data:
                    break

            if not data or data < oggi:
                continue

            orari = parse_orario(riga)
            if not orari:
                continue

            for inizio_h, fine_h in orari:
                eventi.append({
                    "Data":    data,
                    "Materia": "Lezione",
                    "Inizio":  inizio_h,
                    "Fine":    fine_h,
                })

    return eventi


# ── 5. NAVIGAZIONE ──────────────────────────────────────────────────────────
if "pagina" not in st.session_state:
    st.session_state.pagina = "inserimento"

# Nasconde la sidebar di default e aggiunge padding bottom per la navbar
st.markdown("""
<style>
[data-testid="stSidebar"] { display: none; }
[data-testid="collapsedControl"] { display: none; }

/* Spazio in fondo al contenuto per non finire sotto la navbar */
.main .block-container { padding-bottom: 90px !important; }

/* ── Navbar fissa in basso ── */
.bottom-nav {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    height: 62px;
    background: #ffffff;
    border-top: 1px solid #e2e6f0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0;
    z-index: 9999;
    box-shadow: 0 -2px 12px rgba(0,0,0,0.07);
}
.nav-item {
    flex: 1;
    max-width: 80px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    cursor: pointer;
    text-decoration: none;
    padding: 6px 0;
    border-radius: 12px;
    transition: background 0.15s;
}
.nav-item:hover { background: #f0f2f8; }
.nav-icon svg {
    width: 22px; height: 22px;
    fill: none;
    stroke: #9aa0b4;
    stroke-width: 1.7;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: stroke 0.15s;
}
.nav-item.active .nav-icon svg { stroke: #1a1a2e; }
.nav-label {
    font-size: 0.6rem;
    color: #9aa0b4;
    letter-spacing: 0.04em;
    font-family: sans-serif;
    font-weight: 500;
    text-transform: uppercase;
}
.nav-item.active .nav-label { color: #1a1a2e; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

# Leggi parametro URL per cambio pagina
params = st.query_params
if "nav" in params:
    st.session_state.pagina = params["nav"]
    st.query_params.clear()

pagina = st.session_state.pagina

# SVG monocromatici per le 6 icone
ICONE = {
    "inserimento": (
        # Documento con freccia su (upload)
        '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/>'
        '<polyline points="9 15 12 12 15 15"/></svg>'
    ),
    "calendario": (
        # Calendario
        '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>'
        '<line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>'
        '<line x1="3" y1="10" x2="21" y2="10"/></svg>'
    ),
    "vuota1": (
        # Campanella (notifiche — per uso futuro)
        '<svg viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>'
        '<path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>'
    ),
    "vuota2": (
        # Impostazioni
        '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06'
        'a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09'
        'A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83'
        'l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09'
        'A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83'
        'l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09'
        'a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83'
        'l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09'
        'a1.65 1.65 0 0 0-1.51 1z"/></svg>'
    ),
    "vuota3": (
        # Grafico / statistiche
        '<svg viewBox="0 0 24 24"><line x1="18" y1="20" x2="18" y2="10"/>'
        '<line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>'
    ),
    "vuota4": (
        # Utente / profilo
        '<svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>'
        '<circle cx="12" cy="7" r="4"/></svg>'
    ),
}

LABEL_ICONE = {
    "inserimento": "Inserisci",
    "calendario":  "Calendario",
    "vuota1":      "Avvisi",
    "vuota2":      "Impostaz.",
    "vuota3":      "Statistiche",
    "vuota4":      "Profilo",
}

# Navbar HTML con link ?nav=... per cambiare pagina
nav_html = "<div class='bottom-nav'>"
for key, svg in ICONE.items():
    attivo = "active" if pagina == key else ""
    cliccabile = key in ("inserimento", "calendario")
    if cliccabile:
        nav_html += (
            f"<a class='nav-item {attivo}' href='?nav={key}'>"
            f"<span class='nav-icon'>{svg}</span>"
            f"<span class='nav-label'>{LABEL_ICONE[key]}</span>"
            f"</a>"
        )
    else:
        # Icone vuote: non navigano, solo estetiche
        nav_html += (
            f"<div class='nav-item' style='opacity:0.45;cursor:default;'>"
            f"<span class='nav-icon'>{svg}</span>"
            f"<span class='nav-label'>{LABEL_ICONE[key]}</span>"
            f"</div>"
        )
nav_html += "</div>"
st.markdown(nav_html, unsafe_allow_html=True)

# ── PAGINA 1 ─────────────────────────────────────────────────────────────────
if pagina == "inserimento":
    st.title("Inserimento Programmi")
    st.write(
        "Carica un file **PDF** o **TXT**, oppure incolla il testo del programma. "
        "Il parser riconosce automaticamente date, giorni, orari e materie."
    )

    testo_manuale = st.text_area(
        "Testo del programma:",
        placeholder=(
            "Es. 'Corso di Storia dal 15 Giugno al 17 Settembre, "
            "Lunedì e Mercoledì dalle 9:00 alle 11:00'"
        ),
        height=150,
    )

    uploaded_file = st.file_uploader(
        "Oppure carica un file", type=["txt", "pdf"]
    )

    # Anteprima testo estratto dal file
    testo_file = ""
    if uploaded_file:
        if uploaded_file.type == "application/pdf":
            testo_file = estrai_testo_pdf(uploaded_file)
        else:
            testo_file = estrai_testo_txt(uploaded_file)

        with st.expander("📄 Testo estratto dal file (clicca per vedere)"):
            st.text(testo_file[:3000] + ("..." if len(testo_file) > 3000 else ""))

    if st.button("✨ Genera Calendario"):
        testo_da_analizzare = testo_file if testo_file else testo_manuale

        if not testo_da_analizzare.strip():
            st.warning("Inserisci del testo o carica un file prima di procedere.")
        else:
            with st.spinner("Analisi del testo in corso..."):
                nuovi_eventi = parse_programma(testo_da_analizzare)

            if nuovi_eventi:
                st.session_state.calendario_eventi.extend(nuovi_eventi)
                st.success(
                    f"✅ Generati **{len(nuovi_eventi)} eventi** futuri. "
                    "Gli eventi passati sono stati scartati automaticamente."
                )
            else:
                st.error(
                    "⚠️ Non sono riuscito a riconoscere date/orari nel testo. "
                    "Prova a usare un formato come: "
                    "*'Corso di X dal 15 giugno al 17 settembre, "
                    "lunedì e mercoledì dalle 9:00 alle 11:00'*"
                )

# ── PAGINA 2 ─────────────────────────────────────────────────────────────────
elif pagina == "calendario":

    MESI_NOMI = {
        1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile",
        5: "Maggio", 6: "Giugno", 7: "Luglio", 8: "Agosto",
        9: "Settembre", 10: "Ottobre", 11: "Novembre", 12: "Dicembre",
    }
    GIORNI_NOMI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

    # Colori per materia (assegnati dinamicamente)
    PALETTE = [
        "#4F86C6", "#E07B54", "#5BAD8F", "#A66CC9",
        "#D4A843", "#C95B7A", "#4AADB5", "#7B8FA1",
    ]

    st.markdown("""
    <style>
    .settimana-header {
        text-align: center;
        font-size: 1.6rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0.2rem;
    }
    .mese-label {
        text-align: center;
        font-size: 0.95rem;
        color: #555;
        margin-bottom: 1.2rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    .giorno-header {
        background: #1a1a2e;
        color: white;
        border-radius: 10px 10px 0 0;
        padding: 8px 4px 6px 4px;
        text-align: center;
        font-weight: 600;
        font-size: 0.82rem;
        letter-spacing: 0.04em;
    }
    .giorno-numero {
        font-size: 1.5rem;
        font-weight: 800;
        line-height: 1.1;
    }
    .giorno-nome {
        font-size: 0.72rem;
        opacity: 0.85;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .giorno-cella {
        background: #f7f8fc;
        border-radius: 0 0 10px 10px;
        min-height: 130px;
        padding: 6px 4px;
        border: 1.5px solid #e2e6f0;
        border-top: none;
    }
    .giorno-oggi .giorno-header {
        background: #4F86C6;
    }
    .evento-card {
        border-radius: 7px;
        padding: 5px 7px;
        margin-bottom: 5px;
        font-size: 0.75rem;
        color: white;
        line-height: 1.3;
        word-break: break-word;
    }
    .evento-titolo {
        font-weight: 700;
        font-size: 0.78rem;
    }
    .evento-orario {
        opacity: 0.88;
        font-size: 0.7rem;
    }
    .nav-settimana {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 1.5rem;
        margin-bottom: 1rem;
    }
    .vuoto-label {
        color: #aab;
        font-size: 0.72rem;
        text-align: center;
        padding-top: 18px;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Intestazione pagina ──────────────────────────────────────────────────
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

        # ── Indice settimana corrente ────────────────────────────────────────
        if "settimana_offset" not in st.session_state:
            st.session_state.settimana_offset = 0

        # Calcola la prima settimana disponibile (lunedì della settimana del primo evento)
        prima_data = df["Data"].min()
        lunedi_base = prima_data - datetime.timedelta(days=prima_data.weekday())
        lunedi_corrente = lunedi_base + datetime.timedelta(weeks=st.session_state.settimana_offset)
        domenica_corrente = lunedi_corrente + datetime.timedelta(days=6)

        # Conta settimane totali disponibili
        ultima_data = df["Data"].max()
        lunedi_ultima = ultima_data - datetime.timedelta(days=ultima_data.weekday())
        n_settimane = int((lunedi_ultima - lunedi_base).days / 7) + 1

        # ── Navigazione frecce ───────────────────────────────────────────────
        col_prec, col_info, col_succ = st.columns([1, 4, 1])
        with col_prec:
            if st.button("◀", use_container_width=True, disabled=(st.session_state.settimana_offset <= 0)):
                st.session_state.settimana_offset -= 1
                st.rerun()
        with col_info:
            # Mostra mese/i della settimana corrente
            if lunedi_corrente.month == domenica_corrente.month:
                label_mese = f"{MESI_NOMI[lunedi_corrente.month]} {lunedi_corrente.year}"
            else:
                label_mese = (
                    f"{MESI_NOMI[lunedi_corrente.month]} – "
                    f"{MESI_NOMI[domenica_corrente.month]} {domenica_corrente.year}"
                )
            st.markdown(f"<div class='settimana-header'>{label_mese}</div>", unsafe_allow_html=True)
            settimana_num = st.session_state.settimana_offset + 1
            st.markdown(
                f"<div class='mese-label'>Settimana {settimana_num} di {n_settimane} &nbsp;·&nbsp; "
                f"{lunedi_corrente.strftime('%d/%m')} – {domenica_corrente.strftime('%d/%m/%Y')}</div>",
                unsafe_allow_html=True,
            )
        with col_succ:
            if st.button("▶", use_container_width=True,
                         disabled=(st.session_state.settimana_offset >= n_settimane - 1)):
                st.session_state.settimana_offset += 1
                st.rerun()

        # ── Palette colori per materia ───────────────────────────────────────
        tutte_materie = sorted(df["Materia"].unique())
        colori_materia = {m: PALETTE[i % len(PALETTE)] for i, m in enumerate(tutte_materie)}

        # ── Filtro materie ───────────────────────────────────────────────────
        with st.expander("🔍 Filtra materie", expanded=False):
            filtro_materie = st.multiselect(
                "Mostra:", options=tutte_materie, default=list(tutte_materie),
                label_visibility="collapsed"
            )

        # Filtra il df per la settimana corrente e le materie selezionate
        mask = (
            (df["Data"] >= lunedi_corrente) &
            (df["Data"] <= domenica_corrente) &
            (df["Materia"].isin(filtro_materie))
        )
        df_settimana = df[mask]

        # ── Griglia settimanale ──────────────────────────────────────────────
        oggi = datetime.date.today()
        giorni_settimana = [lunedi_corrente + datetime.timedelta(days=i) for i in range(7)]

        # Raccoglie tutte le fasce orarie presenti nella settimana, ordinate
        fasce_settimana = sorted(
            df_settimana[["Inizio", "Fine"]]
            .drop_duplicates()
            .apply(lambda r: (r["Inizio"], r["Fine"]), axis=1)
            .tolist()
        ) if not df_settimana.empty else []

        # Costruisce la griglia come unica tabella HTML
        # Ogni riga = una fascia oraria; ogni colonna = un giorno
        CARD_H = 72   # altezza fissa card in px

        html = """
        <style>
        .cal-table { width:100%; border-collapse:separate; border-spacing:4px 0; table-layout:fixed; }
        .cal-th {
            background:#1a1a2e; color:white;
            border-radius:10px 10px 0 0;
            padding:8px 4px 6px 4px;
            text-align:center; font-size:0.78rem;
        }
        .cal-th.oggi { background:#4F86C6; }
        .cal-num { font-size:1.45rem; font-weight:800; line-height:1.1; }
        .cal-dn  { font-size:0.68rem; opacity:.85; text-transform:uppercase; letter-spacing:.05em; }
        .cal-td {
            background:#f7f8fc;
            border-left:1.5px solid #e2e6f0;
            border-right:1.5px solid #e2e6f0;
            padding:4px 4px;
            vertical-align:top;
            width:14.28%;
        }
        .cal-td-bottom {
            background:#f7f8fc;
            border-left:1.5px solid #e2e6f0;
            border-right:1.5px solid #e2e6f0;
            border-bottom:1.5px solid #e2e6f0;
            border-radius:0 0 10px 10px;
            height:12px;
        }
        .cal-td-vuoto { background:#f7f8fc; border-left:1.5px solid #e2e6f0; border-right:1.5px solid #e2e6f0; padding:4px; }
        .ev {
            border-radius:7px;
            padding:6px 8px;
            color:white;
            font-size:0.74rem;
            line-height:1.35;
            height:""" + str(CARD_H) + """px;
            box-sizing:border-box;
            overflow:hidden;
            display:flex;
            flex-direction:column;
            justify-content:center;
        }
        .ev-titolo { font-weight:700; font-size:0.76rem; }
        .ev-orario { opacity:.88; font-size:0.68rem; margin-top:2px; }
        .ev-vuoto  {
            height:""" + str(CARD_H) + """px;
            background:#eef0f6;
            border-radius:7px;
            border:1.5px dashed #d0d4e8;
        }
        .fascia-label {
            font-size:0.65rem; color:#888;
            text-align:right; padding-right:6px;
            white-space:nowrap; vertical-align:middle;
            width:52px;
        }
        </style>
        <table class="cal-table">
        <thead><tr><td style="width:52px"></td>
        """

        for giorno in giorni_settimana:
            cls = "oggi" if giorno == oggi else ""
            html += (
                f"<th class='cal-th {cls}'>"
                f"<div class='cal-num'>{giorno.day}</div>"
                f"<div class='cal-dn'>{GIORNI_NOMI[giorno.weekday()][:3]}</div>"
                f"</th>"
            )
        html += "</tr></thead><tbody>"

        if not fasce_settimana:
            # Settimana senza eventi
            html += "<tr><td class='fascia-label'></td>"
            for _ in giorni_settimana:
                html += "<td class='cal-td cal-td-bottom' style='height:80px;text-align:center;color:#aab;font-size:0.75rem;padding-top:20px;'>—</td>"
            html += "</tr>"
        else:
            for fascia_idx, (inizio_h, fine_h) in enumerate(fasce_settimana):
                is_ultima = (fascia_idx == len(fasce_settimana) - 1)
                td_class = "cal-td" + (" cal-td-bottom" if is_ultima else "")
                html += f"<tr><td class='fascia-label'>{inizio_h}<br><span style='color:#bbb'>→</span><br>{fine_h}</td>"

                for giorno in giorni_settimana:
                    ev_cella = df_settimana[
                        (df_settimana["Data"] == giorno) &
                        (df_settimana["Inizio"] == inizio_h) &
                        (df_settimana["Fine"] == fine_h)
                    ]
                    if ev_cella.empty:
                        html += f"<td class='{td_class}'><div class='ev-vuoto'></div></td>"
                    else:
                        ev = ev_cella.iloc[0]
                        colore = colori_materia.get(ev["Materia"], "#4F86C6")
                        html += (
                            f"<td class='{td_class}'>"
                            f"<div class='ev' style='background:{colore};'>"
                            f"<div class='ev-titolo'>{ev['Materia']}</div>"
                            f"<div class='ev-orario'>🕐 {inizio_h} – {fine_h}</div>"
                            f"</div></td>"
                        )
                html += "</tr>"

            # Riga di chiusura fondo colonne (bordo arrotondato bottom)
            if not is_ultima:
                html += "<tr><td></td>"
                for _ in giorni_settimana:
                    html += "<td class='cal-td-bottom'></td>"
                html += "</tr>"

        html += "</tbody></table>"
        st.markdown(html, unsafe_allow_html=True)

        # ── Pulsanti elimina (sotto la griglia, per fascia) ──────────────────
        # Streamlit non può mettere button dentro HTML puro,
        # quindi li mostriamo in una sezione separata compatta
        if not df_settimana.empty:
            st.divider()
            st.markdown("**Rimuovi un evento:**")
            for fascia_idx, (inizio_h, fine_h) in enumerate(fasce_settimana):
                for giorno in giorni_settimana:
                    ev_cella = df_settimana[
                        (df_settimana["Data"] == giorno) &
                        (df_settimana["Inizio"] == inizio_h) &
                        (df_settimana["Fine"] == fine_h)
                    ]
                    if not ev_cella.empty:
                        ev = ev_cella.iloc[0]
                        real_idx = df[
                            (df["Data"] == ev["Data"]) &
                            (df["Materia"] == ev["Materia"]) &
                            (df["Inizio"] == ev["Inizio"])
                        ].index
                        if len(real_idx) > 0:
                            colore = colori_materia.get(ev["Materia"], "#4F86C6")
                            c1, c2 = st.columns([5, 1])
                            with c1:
                                st.markdown(
                                    f"<div style='display:flex;align-items:center;gap:8px;padding:3px 0;'>"
                                    f"<div style='width:10px;height:10px;border-radius:3px;background:{colore};flex-shrink:0;'></div>"
                                    f"<span style='font-size:0.82rem;'>"
                                    f"<b>{giorno.strftime('%a %d/%m')}</b> · {ev['Materia']} · {inizio_h}–{fine_h}"
                                    f"</span></div>",
                                    unsafe_allow_html=True,
                                )
                            with c2:
                                if st.button("✕", key=f"del_{real_idx[0]}", help="Rimuovi"):
                                    st.session_state.calendario_eventi.pop(real_idx[0])
                                    st.rerun()

        # ── Legenda colori ───────────────────────────────────────────────────
        st.divider()
        st.markdown("**Legenda materie**")
        leg_cols = st.columns(min(len(tutte_materie), 4))
        for i, materia in enumerate(tutte_materie):
            colore = colori_materia[materia]
            with leg_cols[i % len(leg_cols)]:
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:7px;margin-bottom:4px;'>"
                    f"<div style='width:14px;height:14px;border-radius:4px;"
                    f"background:{colore};flex-shrink:0;'></div>"
                    f"<span style='font-size:0.82rem;'>{materia}</span></div>",
                    unsafe_allow_html=True,
                )
