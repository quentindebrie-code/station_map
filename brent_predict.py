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

# --- ENGINE : DATA ACQUISITION ---
@st.cache_data(ttl=1800)
def fetch_occitan_data():
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
            # Filtre strict Occitanie
            if not cp.startswith(('09', '11', '12', '30', '31', '32', '34', '46', '48', '65', '66', '81', '82')):
                continue
            
            adr = (pdv.findtext('adresse') or "").upper()
            vil = (pdv.findtext('ville') or "").upper()
            
            # Mapping Enseignes pour analyse concurrentielle
            enseigne = "INDÉPENDANT"
            marques = ['TOTAL', 'LECLERC', 'CARREFOUR', 'INTERMARCHE', 'ESSO', 'AVIA', 'BP', 'U', 'CASINO', 'AUCHAN']
            for m in marques:
                if m in adr or m in vil:
                    enseigne = m
                    break

            base = {
                'id': pdv.get('id'),
                'lat': float(pdv.get('latitude')) / 100000 if pdv.get('latitude') else None,
                'lon': float(pdv.get('longitude')) / 100000 if pdv.get('longitude') else None,
                'ville': vil,
                'adresse': adr,
                'enseigne': enseigne,
                'cp': cp
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
        st.error(f"Erreur technique : {e}")
        return pd.DataFrame()

def get_distance(lat1, lon1, lat2, lon2):
    return np.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2) * 111

# --- UI STRATÉGIQUE ---
st.title("🛡️ Hympyr Business Intelligence")
df = fetch_occitan_data()

if not df.empty:
    with st.sidebar:
        st.header("🔍 Localiser mon point de vente")
        
        # 1. Recherche par Ville
        search_city = st.text_input("Ville ou Code Postal", "").upper()
        
        filtered_df = df.copy()
        if search_city:
            filtered_df = df[df['ville'].str.contains(search_city) | df['cp'].str.startswith(search_city)]
        
        # 2. Sélection de la station précise
        if not filtered_df.empty:
            station_list = filtered_df[['id', 'enseigne', 'ville']].drop_duplicates()
            station_options = {f"{r['enseigne']} - {r['ville']} ({r['id']})": r['id'] for _, r in station_list.iterrows()}
            selected_label = st.selectbox("Sélectionnez votre station", options=list(station_options.keys()))
            my_id = station_options[selected_label]
        else:
            st.warning("Aucune station trouvée pour cette recherche.")
            my_id = None

        st.divider()
        fuel = st.selectbox("Carburant cible", df['carburant'].unique())
        radius = st.slider("Rayon de veille (km)", 2, 20, 5)

    if my_id:
        my_data = df[(df['id'] == my_id) & (df['carburant'] == fuel)]
        
        if not my_data.empty:
            me = my_data.iloc[0]
            df_fuel = df[df['carburant'] == fuel].copy()
            df_fuel['dist'] = get_distance(me['lat'], me['lon'], df_fuel['lat'], df_fuel['lon'])
            
            # Définition des concurrents
            comps = df_fuel[(df_fuel['dist'] <= radius) & (df_fuel['id'] != my_id)].copy()

            # --- ANALYSE DE POSITIONNEMENT ---
            avg_price = comps['prix'].mean() if not comps.empty else me['prix']
            cheapest = comps['prix'].min() if not comps.empty else me['prix']
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Mon Prix", f"{me['prix']:.3f}€")
            c2.metric("Moyenne Zone", f"{avg_price:.3f}€", f"{me['prix'] - avg_price:.3f}€", delta_color="inverse")
            c3.metric("Prix Min Zone", f"{cheapest:.3f}€")

            # --- MAP INTERACTIVE ---
            st.subheader(f"Veille concurrentielle autour de {me['ville']}")
            m = folium.Map(location=[me['lat'], me['lon']], zoom_start=13, tiles="cartodbpositron")
            
            # Ma Station (Icône Spéciale)
            folium.Marker(
                [me['lat'], me['lon']],
                icon=folium.Icon(color='black', icon='star', prefix='fa'),
                tooltip="MA STATION"
            ).add_to(m)

            # Concurrents
            for _, row in comps.iterrows():
                # Détection fraîcheur
                is_stale = (datetime.now() - row['maj']).total_seconds() > 172800 # 48h
                
                # Code couleur selon le prix par rapport à moi
                marker_color = "green" if row['prix'] < me['prix'] else "blue"
                if is_stale: marker_color = "lightgray"

                # Info-bulle détaillée
                html = f"""
                <div style="font-family: 'Segoe UI', sans-serif; width: 220px;">
                    <b style="color:#2c3e50; font-size:14px;">{row['enseigne']}</b><br>
                    <span style="color:#7f8c8d; font-size:11px;">{row['adresse'].title()}</span>
                    <hr style="margin:8px 0;">
                    <div style="display:flex; justify-content:space-between;">
                        <span>Prix:</span><b style="font-size:15px;">{row['prix']:.3f}€</b>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:12px;">
                        <span>Distance:</span><span>{row['dist']:.1f} km</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:11px; color:gray; margin-top:5px;">
                        <span>MàJ:</span><span>{row['maj'].strftime('%d/%m %H:%M')}</span>
                    </div>
                    {"<p style='color:#e67e22; font-size:11px; margin-top:5px;'>⚠️ Donnée ancienne (Rupture ?)</p>" if is_stale else ""}
                </div>
                """
                
                folium.Marker(
                    [row['lat'], row['lon']],
                    popup=folium.Popup(html, max_width=250),
                    tooltip=f"{row['enseigne']} : {row['prix']:.3f}€",
                    icon=folium.Icon(color=marker_color, icon='gas-pump', prefix='fa')
                ).add_to(m)

            st_folium(m, width="100%", height=550)

            # --- TABLEAU DE DÉCISION ---
            with st.expander("📊 Détail de la concurrence directe"):
                st.dataframe(
                    comps[['enseigne', 'prix', 'dist', 'maj', 'ville']].sort_values('prix'),
                    column_config={
                        "prix": st.column_config.NumberColumn("Prix", format="%.3f €"),
                        "dist": st.column_config.NumberColumn("Dist. (km)", format="%.1f"),
                        "maj": st.column_config.DatetimeColumn("Mise à jour"),
                    },
                    use_container_width=True, hide_index=True
                )
        else:
            st.info("Cette station ne propose pas ce carburant. Changez de sélection.")

# --- L'ANGLE MORT DE L'EXPERT ---
st.divider()
st.caption("**Conseil Stratégique :** La recherche par ville est utile, mais attention au 'biais de commune'. Un client à la limite de Toulouse et Colomiers se fiche de la ville administrative ; il compare les stations sur son trajet. Ton filtre de rayon (km) est ton meilleur allié pour une tarification réaliste.")
