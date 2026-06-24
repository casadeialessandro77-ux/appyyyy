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


def parse_programma(testo: str) -> list[dict]:
    """
    Analizza il testo completo e restituisce una lista di eventi da aggiungere
    al calendario, escludendo date già passate.
    """
    oggi = datetime.date.today()
    testo_lower = testo.lower()
    eventi = []

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
st.sidebar.title("Menu Navigazione")
pagina = st.sidebar.radio("Vai a:", ["📥 Inserimento", "📅 Visualizza Calendario"])

# ── PAGINA 1 ─────────────────────────────────────────────────────────────────
if pagina == "📥 Inserimento":
    st.title("📥 Inserimento Programmi")
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
elif pagina == "📅 Visualizza Calendario":
    st.title("📅 Il tuo Calendario")

    col_a, col_b = st.columns([6, 1])
    with col_b:
        if st.button("🗑️ Svuota tutto"):
            st.session_state.calendario_eventi = []
            st.rerun()

    if not st.session_state.calendario_eventi:
        st.warning("Il calendario è vuoto. Vai alla pagina di inserimento per generare gli eventi.")
    else:
        df = pd.DataFrame(st.session_state.calendario_eventi)
        df = df.sort_values(by="Data").reset_index(drop=True)

        # Raggruppa per materia per una lettura più chiara
        materie = df["Materia"].unique()
        filtro = st.multiselect("Filtra per materia:", options=materie, default=list(materie))
        df_filtrato = df[df["Materia"].isin(filtro)]

        st.markdown(f"**{len(df_filtrato)} lezioni** in programma")
        st.divider()

        for index, row in df_filtrato.iterrows():
            col1, col2, col3 = st.columns([2, 5, 1])
            with col1:
                st.write(f"📅 **{row['Data'].strftime('%d/%m/%Y')}**")
            with col2:
                st.write(f"📖 *{row['Materia']}* ({row['Inizio']} – {row['Fine']})")
            with col3:
                if st.button("❌", key=f"del_{index}"):
                    st.session_state.calendario_eventi.pop(index)
                    st.rerun()
