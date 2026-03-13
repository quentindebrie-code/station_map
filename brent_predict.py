import streamlit as st
import pandas as pd
import requests
import zipfile
import io
import xml.etree.ElementTree as ET
import folium
from streamlit_folium import st_folium
from datetime import datetime
import numpy as np

# --- MOTEUR DE DONNÉES CONSOLIDÉES ---
@st.cache_data(ttl=1800)
def fetch_full_occitan_data():
    url = "https://donnees.roulez-eco.fr/opendata/instantane"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            with z.open(z.namelist()[0]) as f:
                root = ET.parse(f).getroot()
        
        stations_dict = {}
        for pdv in root.findall('pdv'):
            cp = pdv.get('cp') or ""
            if not cp.startswith(('09', '11', '12', '30', '31', '32', '34', '46', '48', '65', '66', '81', '82')):
                continue
            
            s_id = pdv.get('id')
            adr = (pdv.findtext('adresse') or "").upper()
            vil = (pdv.findtext('ville') or "").upper()
            
            # Identification enseigne
            enseigne = "INDÉPENDANT"
            for m in ['TOTAL', 'LECLERC', 'CARREFOUR', 'INTERMARCHE', 'ESSO', 'AVIA', 'BP', 'U', 'CASINO', 'AUCHAN']:
                if m in adr or m in vil or (m == 'U' and ' SYSTEME U ' in adr):
                    enseigne = m
                    break

            stations_dict[s_id] = {
                'id': s_id,
                'lat': float(pdv.get('latitude')) / 100000 if pdv.get('latitude') else None,
                'lon': float(pdv.get('longitude')) / 100000 if pdv.get('longitude') else None,
                'ville': vil,
                'adresse': adr,
                'enseigne': enseigne,
                'cp': cp,
                'prix_data': {}
            }
            
            for prix in pdv.findall('prix'):
                nom = prix.get('nom')
                stations_dict[s_id]['prix_data'][nom] = {
                    'val': float(prix.get('valeur')),
                    'maj': pd.to_datetime(prix.get('maj'), errors='coerce')
                }
        
        return stations_dict
    except Exception as e:
        st.error(f"Erreur technique : {e}")
        return {}

def get_distance(lat1, lon1, lat2, lon2):
    return np.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2) * 111

# --- INTERFACE ---
st.title("🛡️ Hympyr : Multi-Fuel Intelligence")
all_stations = fetch_full_occitan_data()

if all_stations:
    with st.sidebar:
        st.header("🔍 Ma Station")
        search = st.text_input("Ville ou CP", "TOULOUSE").upper()
        
        filtered = [s for s in all_stations.values() if search in s['ville'] or s['cp'].startswith(search)]
        
        if filtered:
            options = {f"{s['enseigne']} - {s['ville']} ({s['id']})": s['id'] for s in filtered}
            my_id = st.selectbox("Choisir ma station", options=list(options.keys()))
            radius = st.slider("Rayon de veille (km)", 2, 20, 5)
        else:
            st.warning("Aucun résultat.")
            my_id = None

    if my_id:
        me = all_stations[my_id]
        
        # Calcul de la concurrence
        comps = []
        for s_id, s_data in all_stations.items():
            if s_id == my_id: continue
            d = get_distance(me['lat'], me['lon'], s_data['lat'], s_data['lon'])
            if d <= radius:
                s_data['dist'] = d
                comps.append(s_data)

        # --- MAP ---
        m = folium.Map(location=[me['lat'], me['lon']], zoom_start=13, tiles="cartodbpositron")
        folium.Marker([me['lat'], me['lon']], icon=folium.Icon(color='black', icon='star')).add_to(m)

        for s in comps:
            # Construction du Tooltip Multi-carburants
            prix_html = "".join([f"<li><b>{n}:</b> {p['val']:.3f}€</li>" for n, p in s['prix_data'].items()])
            
            html = f"""
            <div style="font-family: sans-serif; width: 200px;">
                <b>{s['enseigne']}</b><br><small>{s['adresse']}</small><hr>
                <ul style="list-style:none; padding:0; margin:0; font-size:12px;">{prix_html}</ul>
                <br><small>Distance: {s['dist']:.1f} km</small>
            </div>
            """
            
            folium.Marker(
                [s['lat'], s['lon']],
                popup=folium.Popup(html, max_width=250),
                icon=folium.Icon(color='blue', icon='gas-pump', prefix='fa')
            ).add_to(m)

        st_folium(m, width="100%", height=500)

        # --- TABLEAU DE DÉTAILS MULTI-PRIX ---
        st.subheader("📋 Comparatif complet de la zone")
        
        table_data = []
        all_fuel_types = sorted(list(set(f for s in comps + [me] for f in s['prix_data'].keys())))
        
        for s in [me] + sorted(comps, key=lambda x: x['dist']):
            row = {
                "Station": f"{s['enseigne']} ({s['id']})",
                "Ville": s['ville'],
                "Dist.": 0 if s['id'] == my_id else round(s['dist'], 1)
            }
            for f in all_fuel_types:
                row[f] = s['prix_data'].get(f, {}).get('val')
            table_data.append(row)
            
        df_table = pd.DataFrame(table_data)
        st.dataframe(df_table, use_container_width=True, hide_index=True)

else:
    st.error("Données indisponibles.")

# --- ANALYSE BRUTALE ---
st.divider()
st.info("**Stratégie Cross-Fuel :** Regarde ton tableau. Si tu es le moins cher sur le Gazole mais le plus cher sur le SP95, tu n'attires que les professionnels (camionnettes) et tu rates les familles. Un gérant expert équilibre ses marges sur l'ensemble du totem, pas par produit isolé.")
