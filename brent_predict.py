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

# --- MOTEUR DE DONNÉES ---
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
            
            # Identification enseigne (Correction pour 'U')
            enseigne = "INDÉPENDANT"
            marques = ['TOTAL', 'LECLERC', 'CARREFOUR', 'INTERMARCHE', 'ESSO', 'AVIA', 'BP', 'CASINO', 'AUCHAN']
            for m in marques:
                if m in adr or m in vil:
                    enseigne = m
                    break
            
            if enseigne == "INDÉPENDANT":
                if " SYSTEME U " in adr or " SUPER U " in adr or " HYPER U " in adr or " MARCHE U " in adr:
                    enseigne = "U"

            stations_dict[s_id] = {
                'id': s_id,
                'lat': float(pdv.get('latitude')) / 100000 if pdv.get('latitude') else None,
                'lon': float(pdv.get('longitude')) / 100000 if pdv.get('longitude') else None,
                'ville': vil,
                'adresse': adr,
                'enseigne': enseigne,
                'cp': cp,
                'prix_data': {prix.get('nom'): {'val': float(prix.get('valeur')), 'maj': pd.to_datetime(prix.get('maj'), errors='coerce')} 
                             for prix in pdv.findall('prix')}
            }
        return stations_dict
    except Exception as e:
        st.error(f"Erreur technique : {e}")
        return {}

def get_distance(lat1, lon1, lat2, lon2):
    if None in [lat1, lon1, lat2, lon2]: return 999
    return np.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2) * 111

# --- INTERFACE ---
st.title("🛡️ Hympyr : Multi-Fuel Intelligence")
all_stations = fetch_full_occitan_data()

if all_stations:
    with st.sidebar:
        st.header("🔍 Ma Station")
        search = st.text_input("Ville ou CP", "TOULOUSE").upper()
        
        filtered = [s for s in all_stations.values() if search in s['ville'] or s['cp'].startswith(search)]
        
        my_id = None
        if filtered:
            options = {f"{s['enseigne']} - {s['ville']} ({s['id']})": s['id'] for s in filtered}
            selected_label = st.selectbox("Choisir ma station", options=list(options.keys()))
            my_id = options[selected_label]
        else:
            st.warning("Aucun résultat pour cette recherche.")

        radius = st.slider("Rayon de veille (km)", 2, 20, 5)

    # CORRECTION DU KEYERROR : Vérifier si my_id existe dans le dictionnaire actuel
    if my_id and my_id in all_stations:
        me = all_stations[my_id]
        
        # Calcul de la concurrence
        comps = []
        for s_id, s_data in all_stations.items():
            if s_id == my_id: continue
            d = get_distance(me['lat'], me['lon'], s_data['lat'], s_data['lon'])
            if d <= radius:
                s_data_copy = s_data.copy()
                s_data_copy['dist'] = d
                comps.append(s_data_copy)

        # --- MAP ---
        m = folium.Map(location=[me['lat'], me['lon']], zoom_start=13, tiles="cartodbpositron")
        folium.Marker([me['lat'], me['lon']], 
                      icon=folium.Icon(color='black', icon='star', prefix='fa'),
                      tooltip="MA STATION").add_to(m)

        for s in comps:
            prix_items = [f"<li><b>{n}:</b> {p['val']:.3f}€</li>" for n, p in s['prix_data'].items()]
            prix_html = "".join(prix_items) if prix_items else "<li>Aucun prix dispo</li>"
            
            html = f"""
            <div style="font-family: sans-serif; width: 180px;">
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

        st_folium(m, width="100%", height=500, key="main_map")

        # --- TABLEAU ---
        st.subheader("📋 Comparatif complet de la zone")
        all_fuel_types = sorted(list(set(f for s in comps + [me] for f in s['prix_data'].keys())))
        
        table_data = []
        for s in [me] + sorted(comps, key=lambda x: x['dist']):
            row = {"Station": f"{s['enseigne']}", "Ville": s['ville'], "Dist.": 0 if s['id'] == my_id else round(s['dist'], 1)}
            for f in all_fuel_types:
                row[f] = s['prix_data'].get(f, {}).get('val')
            table_data.append(row)
            
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
    else:
        st.info("Sélectionnez une station dans la barre latérale pour lancer l'analyse.")

else:
    st.error("Échec du chargement des données. L'API gouvernementale est peut-être saturée.")
