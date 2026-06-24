import streamlit as st
import datetime
import pandas as pd

# 1. IMPOSTAZIONI DELLA PAGINA & MEMORIA
st.set_page_config(page_title="Pianificatore IA", page_icon="📅", layout="centered")

# Creiamo un database temporaneo nella memoria del sito per non perdere i dati quando ti sposti tra le pagine
if "calendario_eventi" not in st.session_state:
    st.session_state.calendario_eventi = []

# 2. NAVIGAZIONE (MENU LATERALE)
st.sidebar.title("Menu Navigazione")
pagina = st.sidebar.radio("Vai a:", ["📥 Inserimento e IA", "📅 Visualizza Calendario"])

# --- PAGINA 1: INSERIMENTO E IA ---
if pagina == "📥 Inserimento e IA":
    st.title("📥 Inserimento Programmi")
    st.write("Carica un documento o scrivi il programma per generare il calendario automatico.")

    # Input manuale o caricamento testo
    programma_testo = st.text_area(
        "Incolla qui il testo del programma (es. 'Corso di Storia dal 15 Giugno al 17 Settembre, Lunedì e Mercoledì dalle 9:00 alle 11:00'):",
        height=150
    )
    
    uploaded_file = st.file_uploader("Oppure carica un file", type=["txt", "pdf"])

    if st.button("✨ Genera Calendario con IA"):
        st.info("L'IA sta elaborando i dati giorno per giorno... (Simulazione Algoritmo)")
        
        # QUI IN FUTURO CI SARÀ LA CHIAMATA API ALL'IA.
        # L'IA prenderà la data di inizio (15 Giugno) e fine (17 Settembre), calcolerà tutti i giorni intermedi
        # e creerà una lista. Per ora simuliamo questa generazione automatica:
        
        data_inizio = datetime.date(2026, 6, 15)
        data_fine = datetime.date(2026, 9, 17)
        
        nuovi_eventi = []
        corrente = data_inizio
        
        # L'algoritmo (o l'IA) genera i singoli giorni della settimana (es. ogni Lunedì)
        while corrente <= data_fine:
            if corrente.weekday() == 0:  # 0 = Lunedì
                nuovi_eventi.append({
                    "Data": corrente,
                    "Materia": "Storia Contemporanea",
                    "Inizio": "09:00",
                    "Fine": "11:00"
                })
            elif corrente.weekday() == 2:  # 2 = Mercoledì
                nuovi_eventi.append({
                    "Data": corrente,
                    "Materia": "Storia Contemporanea",
                    "Inizio": "14:00",
                    "Fine": "16:00"
                })
            corrente += datetime.timedelta(days=1)
        
        # Salviamo gli eventi generati nella memoria del sito
        st.session_state.calendario_eventi.extend(nuovi_eventi)
        st.success(f"Generati con successo {len(nuovi_eventi)} eventi dal {data_inizio} al {data_fine}!")

# --- PAGINA 2: VISUALIZZA CALENDARIO & RIMOZIONE ---
elif pagina == "📅 Visualizza Calendario":
    st.title("📅 Il tuo Calendario Generato")
    
    if not st.session_state.calendario_eventi:
        st.warning("Il calendario è vuoto. Vai alla pagina di inserimento per generare gli eventi.")
    else:
        st.write("Ecco l'elenco completo delle tue lezioni giorno per giorno. Puoi rimuovere i singoli elementi se necessario.")
        
        # Trasformiamo i dati in un formato tabellare (DataFrame) per mostrarli puliti
        df = pd.DataFrame(st.session_state.calendario_eventi)
        
        # Ordiniamo per data
        df = df.sort_values(by="Data").reset_index(drop=True)
        
        # Mostriamo la lista all'utente con un ciclo per permettere la cancellazione
        for index, row in df.iterrows():
            col1, col2, col3 = st.columns([2, 5, 1])
            
            with col1:
                st.write(f"📅 **{row['Data'].strftime('%d/%m/%Y')}**")
            with col2:
                st.write(f"📖 *{row['Materia']}* ({row['Inizio']} - {row['Fine']})")
            with col3:
                # Se clicchi il bottone "Elimina", rimuove l'elemento dalla memoria
                if st.button("❌", key=f"del_{index}"):
                    st.session_state.calendario_eventi.pop(index)
                    st.rerun() # Ricarica la pagina per aggiornare la lista visiva
