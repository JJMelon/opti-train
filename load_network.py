"""
load_and_visualize_amtrak.py

Downloads the Amtrak GTFS feed and visualizes the multi-stretch
rail network as a graph, ready for Lagrangian relaxation extension.

Dependencies:
    pip install pandas matplotlib networkx requests gtfs-kit
"""

import zipfile, io, urllib.request
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np

# ── 1. LOAD GTFS ──────────────────────────────────────────────────────────────

GTFS_URL = "https://transitfeeds.com/p/amtrak/1077/latest/download"
# Fallback: manually download from https://mobilitydatabase.org and set path:
LOCAL_PATH = "amtrak_gtfs.zip"   # ← set this if offline

def load_gtfs(url=GTFS_URL, local=LOCAL_PATH):
    """Load GTFS tables from URL or local ZIP."""
    try:
        print(f"Downloading GTFS from {url} ...")
        resp = urllib.request.urlopen(url, timeout=15)
        zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    except Exception as e:
        print(f"Download failed ({e}), trying local file {local}")
        zf = zipfile.ZipFile(local)

    def read(name):
        return pd.read_csv(zf.open(name), dtype=str)

    stops      = read("stops.txt")
    routes     = read("routes.txt")
    trips      = read("trips.txt")
    stop_times = read("stop_times.txt")
    return stops, routes, trips, stop_times


stops, routes, trips, stop_times = load_gtfs()

# ── 2. BUILD ROUTE→STOP SEQUENCE GRAPH ────────────────────────────────────────

# Merge trips → routes → stop_times → stops
st = stop_times.merge(trips[["trip_id","route_id","trip_headsign"]], on="trip_id")
st = st.merge(stops[["stop_id","stop_name","stop_lat","stop_lon"]], on="stop_id")
st["stop_sequence"] = st["stop_sequence"].astype(int)
st = st.sort_values(["trip_id", "stop_sequence"])

# Build directed graph: edges are consecutive station pairs on a trip
G = nx.DiGraph()

# Add station nodes
for _, row in stops.iterrows():
    G.add_node(row["stop_id"],
               name=row["stop_name"],
               lat=float(row["stop_lat"]),
               lon=float(row["stop_lon"]))

# Add edges (one per consecutive stop-pair per route; deduplicated)
edge_routes = {}   # (u,v) → set of route_ids
for trip_id, grp in st.groupby("trip_id"):
    grp = grp.sort_values("stop_sequence")
    route_id = grp.iloc[0]["route_id"]
    pairs = list(zip(grp["stop_id"].tolist(), grp["stop_id"].tolist()[1:]))
    for u, v in pairs:
        key = (u, v)
        edge_routes.setdefault(key, set()).add(route_id)

for (u, v), rids in edge_routes.items():
    G.add_edge(u, v, routes=rids, n_routes=len(rids))

print(f"Graph: {G.number_of_nodes()} stations, {G.number_of_edges()} directed edges")

# ── 3. IDENTIFY MULTI-STRETCH JUNCTIONS ───────────────────────────────────────
# A junction is a node with degree > 2 in the undirected sense — where
# multiple lines diverge, exactly analogous to where single-track stretches
# in the paper would need coupling/coordination constraints.

UG = G.to_undirected()
junctions = [n for n in UG.nodes if UG.degree(n) > 2]
print(f"Network junctions (branching stations): {len(junctions)}")
for j in junctions[:10]:
    print(f"  {G.nodes[j]['name']}  (degree {UG.degree(j)})")

# ── 4. VISUALIZE ──────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 2, figsize=(18, 8))
fig.suptitle("Amtrak Rail Network — Multi-Stretch Graph", fontsize=14, fontweight="bold")

# Geographic layout (lon, lat)
pos = {n: (float(G.nodes[n]["lon"]), float(G.nodes[n]["lat"]))
       for n in G.nodes}

# ── Panel A: full network ──
ax = axes[0]
ax.set_title("Full Network (geographic)", fontsize=11)
ax.set_facecolor("#f0f0f0")

# colour edges by number of overlapping routes (proxy for track contention)
edge_list = list(G.edges())
weights   = [G[u][v]["n_routes"] for u, v in edge_list]
max_w     = max(weights) if weights else 1
colors    = [cm.plasma(w / max_w) for w in weights]

nx.draw_networkx_edges(G, pos, edgelist=edge_list, edge_color=colors,
                       width=1.2, arrows=False, alpha=0.7, ax=ax)
nx.draw_networkx_nodes(G, pos,
    nodelist=[n for n in G.nodes if n not in junctions],
    node_size=15, node_color="#2196F3", alpha=0.7, ax=ax)
nx.draw_networkx_nodes(G, pos,
    nodelist=junctions,
    node_size=60, node_color="#FF5722", alpha=0.9, ax=ax)

# Label junctions only
junction_labels = {n: G.nodes[n]["name"].split("/")[0][:12] for n in junctions}
nx.draw_networkx_labels(G, pos, labels=junction_labels,
                        font_size=5.5, font_color="#111", ax=ax)

ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
sm = plt.cm.ScalarMappable(cmap=cm.plasma,
     norm=plt.Normalize(vmin=1, vmax=max_w))
sm.set_array([])
plt.colorbar(sm, ax=ax, shrink=0.6, label="Overlapping routes on segment")

# ── Panel B: Northeast Corridor subgraph (most congested stretch) ──
ax2 = axes[1]
ax2.set_title("Northeast Corridor Sub-network\n(highest contention — key for multi-stretch ILP)", fontsize=11)
ax2.set_facecolor("#f0f0f0")

# Filter to rough NEC bounding box
NEC_BBOX = dict(lat_min=38.5, lat_max=42.5, lon_min=-75.5, lon_max=-70.5)
nec_nodes = [n for n in G.nodes
             if NEC_BBOX["lat_min"] < float(G.nodes[n]["lat"]) < NEC_BBOX["lat_max"]
             and NEC_BBOX["lon_min"] < float(G.nodes[n]["lon"]) < NEC_BBOX["lon_max"]]
SG = G.subgraph(nec_nodes)

pos_nec = {n: (float(G.nodes[n]["lon"]), float(G.nodes[n]["lat"])) for n in SG.nodes}
junc_nec = [n for n in SG.nodes if UG.degree(n) > 2]

e_nec   = list(SG.edges())
w_nec   = [SG[u][v]["n_routes"] for u, v in e_nec]
c_nec   = [cm.plasma(w / max_w) for w in w_nec]

nx.draw_networkx_edges(SG, pos_nec, edgelist=e_nec, edge_color=c_nec,
                       width=2.0, arrows=True, arrowsize=8, alpha=0.8, ax=ax2)
nx.draw_networkx_nodes(SG, pos_nec,
    nodelist=[n for n in SG.nodes if n not in junc_nec],
    node_size=40, node_color="#2196F3", alpha=0.8, ax=ax2)
nx.draw_networkx_nodes(SG, pos_nec,
    nodelist=junc_nec, node_size=120, node_color="#FF5722", alpha=0.95, ax=ax2)

nec_labels = {n: G.nodes[n]["name"].split("/")[0][:14] for n in SG.nodes}
nx.draw_networkx_labels(SG, pos_nec, labels=nec_labels,
                        font_size=6, font_color="#111", ax=ax2)
ax2.set_xlabel("Longitude"); ax2.set_ylabel("Latitude")

plt.tight_layout()
plt.savefig("amtrak_network.png", dpi=150, bbox_inches="tight")
plt.show()
print("Saved amtrak_network.png")

# ── 5. PRINT ILP-RELEVANT SUMMARY ────────────────────────────────────────────

n_routes   = routes["route_id"].nunique()
n_trips    = trips["trip_id"].nunique()
n_stations = stops["stop_id"].nunique()
n_shared   = sum(1 for (u,v) in G.edges if G[u][v]["n_routes"] > 1)

print("\n── ILP Problem Size Indicators ──────────────────────────────")
print(f"  Routes (train services):   {n_routes}")
print(f"  Trips (individual runs):   {n_trips}")
print(f"  Stations (nodes):          {n_stations}")
print(f"  Shared-track edge pairs:   {n_shared}  ← these need capacity constraints")
print(f"  Junction stations:         {len(junctions)}  ← Lagrange coupling points")