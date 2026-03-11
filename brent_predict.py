import streamlit as st
import pandas as pd
import requests
import zipfile
import io
import xml.etree.ElementTree as ET
import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="Hympyr Fuel Intelligence", layout="wide")

@st.cache_data(ttl=3600)
def fetch_all_fuel_data():
    url = "https://donnees.roulez-eco.fr/opendata/instantane"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            xml_filename = z.namelist()[0]
            with z.open(xml_filename) as f:
                tree = ET.parse(f)
                root = tree.getroot()
        
        stations = []
        for pdv in root.findall('pdv'):
            adresse = pdv.findtext('adresse') or ""
            ville = (pdv.findtext('ville') or "N/A").upper()
            
            enseigne = "Indépendant / NC"
            marques = ['TOTAL', 'LECLERC', 'CARREFOUR', 'INTERMARCHE', 'ESSO', 'AVIA', 'BP', 'SYSTEME U', 'CASINO', 'AUCHAN']
            for m in marques:
                if m in adresse.upper() or m in ville:
                    enseigne = m
                    break

            base_info = {
                'id': pdv.get('id'),
                'enseigne': enseigne,
                'adresse': adresse,
                'lat': float(pdv.get('latitude')) / 100000 if pdv.get('latitude') else 0,
                'lon': float(pdv.get('longitude')) / 100000 if pdv.get('longitude') else 0,
                'cp': pdv.get('cp'),
                'ville': ville
            }
            
            for prix in pdv.findall('prix'):
                st_data = base_info.copy()
                st_data['carburant'] = prix.get('nom')
                st_data['valeur'] = float(prix.get('valeur'))
                # Conversion de la date de mise à jour en objet datetime
                try:
                    st_data['maj'] = pd.to_datetime(prix.get('maj'))
                except:
                    st_data['maj'] = None
                stations.append(st_data)
                
        return pd.DataFrame(stations)
    except Exception as e:
        st.error(f"Erreur : {e}")
        return pd.DataFrame()

# --- LOGIQUE MÉTIER ---
st.title("Mapping des stations-essence")

df = fetch_all_fuel_data()

if not df.empty:
    with st.sidebar:
        st.header("⚙️ Paramètres")
        fuel_choice = st.selectbox("Carburant", sorted(df['carburant'].unique()))
        
        # NOUVEAU : Filtre de récence
        max_days = st.slider("Récence max (jours)", 1, 30, 7)
        limit_date = datetime.now() - timedelta(days=max_days)
        
        dept = st.text_input("Département", value="")
        city_query = st.text_input("Ville", value="").upper()
        
        # Application des filtres
        df_filtered = df[df['carburant'] == fuel_choice].copy()
        
        # Filtre de récence appliqué ici
        df_filtered = df_filtered[df_filtered['maj'] >= limit_date]
        
        if dept:
            df_filtered = df_filtered[df_filtered['cp'].str.startswith(dept, na=False)]
        if city_query:
            df_filtered = df_filtered[df_filtered['ville'].str.contains(city_query, na=False)]

    if not df_filtered.empty:
        # Metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("Prix Moyen", f"{df_filtered['valeur'].mean():.3f} €")
        c2.metric("Prix Min", f"{df_filtered['valeur'].min():.3f} €")
        c3.metric("Stations fraîches", len(df_filtered))

        # --- CARTE ---
        st.subheader(f"📍 Stations mises à jour depuis {max_days} jours")
        df_map = df_filtered[(df_filtered['lat'] != 0) & (df_filtered['lon'] != 0)]
        
        if not df_map.empty:
            m = folium.Map(location=[df_map['lat'].mean(), df_map['lon'].mean()], zoom_start=6)
            marker_cluster = MarkerCluster().add_to(m)
            for _, row in df_map.head(500).iterrows():
                folium.Marker(
                    location=[row['lat'], row['lon']],
                    popup=f"{row['enseigne']}<br>{row['valeur']}€<br>MàJ: {row['maj'].strftime('%d/%m %H:%M')}",
                ).add_to(marker_cluster)
            st_folium(m, width="100%", height=400, returned_objects=[])

        # --- TABLEAU ---
        st.subheader("📋 Détail des stations")
        st.dataframe(
            df_filtered[['valeur', 'enseigne', 'adresse', 'ville', 'maj']].sort_values('valeur'),
            column_config={
                "valeur": st.column_config.NumberColumn("Prix", format="%.3f €"),
                "maj": st.column_config.DatetimeColumn("Dernière MàJ", format="DD/MM/YYYY HH:mm"),
            },
            use_container_width=True, hide_index=True
        )
    else:
        st.warning(f"Aucune donnée trouvée mise à jour depuis moins de {max_days} jours.")

# --- ANALYSE DE L'EXPERT ---
st.divider()
st.info("**Angle mort identifié :** Les stations qui ne mettent pas à jour leurs prix pendant 7 jours sont souvent soit en rupture, soit fermées, soit pratiquent des prix fixes (rare). En logistique, ignorer la date de mise à jour, c'est envoyer un chauffeur vers une pompe fantôme.")
