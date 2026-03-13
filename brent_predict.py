import streamlit as st
import pandas as pd
import requests
import zipfile
import io
import xml.etree.ElementTree as ET
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta
import numpy as np

# --- MOTEUR DE DONNÉES ---
@st.cache_data(ttl=1800)
def fetch_smart_data():
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
            if not cp.startswith(('09', '11', '12', '30', '31', '32', '34', '46', '48', '65', '66', '81', '82')):
                continue
            
            # Détection Enseigne
            adr = (pdv.findtext('adresse') or "").upper()
            vil = (pdv.findtext('ville') or "").upper()
            enseigne = "INDÉPENDANT"
            for m in ['TOTAL', 'LECLERC', 'CARREFOUR', 'INTERMARCHE', 'ESSO', 'AVIA', 'BP', 'U', 'CASINO', 'AUCHAN']:
                if m in adr or m in vil:
                    enseigne = m
                    break

            base = {
                'id': pdv.get('id'),
                'lat': float(pdv.get('latitude')) / 100000 if pdv.get('latitude') else None,
                'lon': float(pdv.get('longitude')) / 100000 if pdv.get('longitude') else None,
                'ville': vil,
                'adresse': adr,
                'enseigne': enseigne
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
        st.error(f"Erreur : {e}")
        return pd.DataFrame()

def haversine(lat1, lon1, lat2, lon2):
    return np.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2) * 111

# --- INTERFACE ---
st.set_page_config(page_title="Hympyr - Concurrent Intelligence", layout="wide")
df = fetch_smart_data()

if not df.empty:
    with st.sidebar:
        st.title("🛡️ Contrôle")
        my_id = st.text_input("Mon ID Station", value=df['id'].iloc[0])
        fuel = st.selectbox("Carburant", df['carburant'].unique())
        radius = st.slider("Rayon d'analyse (km)", 2, 20, 8)

    my_data = df[(df['id'] == my_id) & (df['carburant'] == fuel)]
    
    if not my_data.empty:
        me = my_data.iloc[0]
        df_fuel = df[df['carburant'] == fuel].copy()
        df_fuel['dist'] = haversine(me['lat'], me['lon'], df_fuel['lat'], df_fuel['lon'])
        comps = df_fuel[(df_fuel['dist'] <= radius) & (df_fuel['id'] != my_id)].copy()

        # Dashboard
        c1, c2, c3 = st.columns(3)
        c1.metric("Prix Ciblé", f"{me['prix']:.3f}€")
        c2.metric("Moyenne Zone", f"{comps['prix'].mean():.3f}€")
        c3.metric("Concurrents", len(comps))

        # --- CARTE AVANCÉE ---
        m = folium.Map(location=[me['lat'], me['lon']], zoom_start=13, tiles="cartodbpositron")
        
        # Icône pour Ma Station
        folium.Marker(
            [me['lat'], me['lon']],
            icon=folium.Icon(color='darkred', icon='home', prefix='fa'),
            tooltip="MA STATION (Focus)"
        ).add_to(m)

        for _, row in comps.iterrows():
            # Logique de fraîcheur
            is_stale = (datetime.now() - row['maj']).total_seconds() > 172800 # 48h
            color = "orange" if is_stale else ("green" if row['prix'] < me['prix'] else "blue")
            
            # HTML POPUP (L'info détaillée que tu voulais)
            html = f"""
            <div style="font-family: Arial, sans-serif; width: 200px;">
                <h4 style="margin-bottom:5px; color:#2c3e50;">{row['enseigne']}</h4>
                <hr style="margin:5px 0;">
                <b>Prix :</b> <span style="font-size:1.2em; color:#e67e22;">{row['prix']:.3f}€</span><br>
                <b>Distance :</b> {row['dist']:.1f} km<br>
                <b>MAJ :</b> {row['maj'].strftime('%d/%m %H:%M')}<br>
                <p style="font-size:0.8em; color:gray;"><i>{row['adresse'].title()}</i></p>
                {"<b style='color:red;'>⚠️ Donnée suspecte (Périmée)</b>" if is_stale else ""}
            </div>
            """
            
            folium.Marker(
                [row['lat'], row['lon']],
                popup=folium.Popup(html, max_width=250),
                tooltip=f"{row['enseigne']} - {row['prix']}€",
                icon=folium.Icon(color=color, icon='gas-pump', prefix='fa')
            ).add_to(m)

        st_folium(m, width="100%", height=600)
    else:
        st.warning("ID non trouvé en Occitanie.")
