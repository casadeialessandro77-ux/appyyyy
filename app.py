import streamlit as st
import datetime

# Configurazione della pagina (ottimizzata per lo schermo dell'iPhone)
st.set_page_config(page_title="Assistente IA", page_icon="🤖", layout="centered")

st.title("🤖 Il tuo Assistente")
st.write("Carica un documento per estrarre le scadenze.")

# 1. Caricamento del File
uploaded_file = st.file_uploader("Scegli un file (PDF, Immagine, Testo)", type=["pdf", "png", "jpg", "txt"])

if uploaded_file is not None:
    st.success("File caricato con successo!")
    
    # Per ora simuliamo l'azione dell'IA prima di collegare le chiavi API a pagamento
    st.subheader("Visualizzazione Scadenze Trovate (Simulazione):")
    
    # Creiamo un esempio di ciò che l'IA estrarrà dal file
    scadenza_finta = {
        "Titolo": "Consegna Progetto X",
        "Data": datetime.date(2026, 7, 15),
        "Nota": "Estratto dal documento caricato."
    }
    
    st.info(f"📅 **{scadenza_finta['Titolo']}**\n\nScadenza: {scadenza_finta['Data']}\n\n_{scadenza_finta['Nota']}_")
    
    # 2. Bottone per inviare al Calendario
    if st.button("🗓️ Aggiungi al Calendario Web"):
        # Qui in futuro inseriremo il codice per inviare i dati a Google Calendar via API
        st.success(f"Evento '{scadenza_finta['Titolo']}' programmato per il {scadenza_finta['Data']}!")