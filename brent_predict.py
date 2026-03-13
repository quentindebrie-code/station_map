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
import numpy as np

# --- CONFIGURATION & DATA ENGINE ---
st.set_page_config(page_title="Hympyr Business Intel - Occitanie", layout="wide")

@st.cache_data(ttl=1800)
def fetch_and_process_data():
    url = "https://donnees.roulez-eco.fr/opendata/instantane"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            with z.open(z.namelist()[0]) as f:
                root = ET.parse(f).getroot()
        
        data = []
        for pdv in root.findall('pdv'):
            cp = pdv.get('cp') or ""
            # Focus Occitanie (Départements 09, 11, 12, 30, 31, 32, 34, 46, 48, 65, 66, 81, 82)
            if not cp.startswith(('09', '11', '12', '30', '31', '32', '34', '46', '48', '65', '66', '81', '82')):
                continue
                
            base = {
                'id': pdv.get('id'),
                'lat': float(pdv.get('latitude')) / 100000 if pdv.get('latitude') else None,
                'lon': float(pdv.get('longitude')) / 100000 if pdv.get('longitude') else None,
                'ville': (pdv.findtext('ville') or "NC").upper(),
                'adresse': pdv.findtext('adresse') or ""
            }
            
            for prix in pdv.findall('prix'):
                d = base.copy()
                d.update({
                    'carburant': prix.get('nom'),
                    'prix': float(prix.get('valeur')),
                    'maj': pd.to_datetime(prix.get('maj'), errors='coerce')
                })
                data.append(d)
        return pd.DataFrame(data).dropna(subset=['lat', 'lon', 'prix'])
    except Exception as e:
        st.error(f"Erreur d'acquisition : {e}")
        return pd.DataFrame()

def haversine(lat1, lon1, lat2, lon2):
    # Calcul de distance simplifié pour performance
    return np.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2) * 111

# --- INTERFACE DE DÉCISION ---
st.title("🚀 Hympyr : Yield Management Carburant")
st.markdown("---")

df = fetch_and_process_data()

if not df.empty:
    with st.sidebar:
        st.header("🎯 Ma Station")
        my_station_id = st.text_input("ID Station (PDV)", value=df['id'].iloc[0])
        fuel_type = st.selectbox("Type de Carburant", df['carburant'].unique())
        radius = st.slider("Zone de chalandise (km)", 2, 30, 10)
        
    # Isolation de ma station
    my_data = df[(df['id'] == my_station_id) & (df['carburant'] == fuel_type)]
    
    if not my_data.empty:
        my_lat, my_lon = my_data.iloc[0]['lat'], my_data.iloc[0]['lon']
        my_price = my_data.iloc[0]['prix']

        # Calcul de la concurrence dans le rayon
        df_fuel = df[df['carburant'] == fuel_type].copy()
        df_fuel['dist'] = haversine(my_lat, my_lon, df_fuel['lat'], df_fuel['lon'])
        competitors = df_fuel[(df_fuel['dist'] <= radius) & (df_fuel['id'] != my_station_id)]

        # --- KPI STRATÉGIQUES ---
        avg_market = competitors['prix'].mean()
        delta = my_price - avg_market
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mon Prix", f"{my_price:.3f} €")
        c2.metric("Moyenne Zone", f"{avg_market:.3f} €", f"{delta:.3f} €", delta_color="inverse")
        
        # Alerte Rupture : Stations sans MAJ depuis 48h
        stale_limit = datetime.now() - timedelta(hours=48)
        ruptures = competitors[competitors['maj'] < stale_limit]
        c3.metric("Ruptures probables", len(ruptures), help="Stations n'ayant pas mis à jour leurs prix depuis 48h")
        
        cheaper_count = len(competitors[competitors['prix'] < my_price])
        c4.metric("Position", f"{cheaper_count + 1} / {len(competitors) + 1}", "Rang prix")

        # --- MAP DE POSITIONNEMENT ---
        col_left, col_right = st.columns([2, 1])
        
        with col_left:
            st.subheader("📍 Mapping de proximité")
            m = folium.Map(location=[my_lat, my_lon], zoom_start=13)
            
            # Ma station
            folium.Marker(
                [my_lat, my_lon], 
                popup="MOI", 
                icon=folium.Icon(color='red', icon='star')
            ).add_to(m)
            
            # Concurrents
            for _, row in competitors.iterrows():
                color = 'green' if row['prix'] < my_price else 'blue'
                icon = 'info-sign' if row['maj'] > stale_limit else 'warning-sign'
                folium.Marker(
                    [row['lat'], row['lon']],
                    popup=f"{row['prix']}€ - {row['id']}",
                    icon=folium.Icon(color=color, icon=icon)
                ).add_to(m)
            st_folium(m, width="100%", height=450, returned_objects=[])

        with col_right:
            st.subheader("📊 Top 5 Concurrents")
            top_comp = competitors.sort_values('prix').head(5)[['prix', 'dist', 'ville']]
            st.table(top_comp)
            
            if delta < -0.05:
                st.success("💡 Opportunité : Vous êtes très bas. Possibilité de remonter de 0.02€ sans perdre votre rang.")
            elif delta > 0.02:
                st.error("⚠️ Alerte : Vous sortez du tunnel de prix local. Risque de perte de volume.")

    else:
        st.warning("Entrez un ID de station valide présent en Occitanie pour activer l'analyse.")
        st.info("Exemples d'ID en base : " + ", ".join(df['id'].head(5).tolist()))
else:
    st.error("Impossible de charger les données. Vérifiez l'URL de l'Open Data.")

# --- ANALYSE SANS FILTRE ---
st.divider()
st.sidebar.info(f"Dernière synchro : {datetime.now().strftime('%H:%M:%S')}")
