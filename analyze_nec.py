import pandas as pd
import os

gtfs_path = "gtfs"

# Load data
stops = pd.read_csv(os.path.join(gtfs_path, "stops.txt"))
routes = pd.read_csv(os.path.join(gtfs_path, "routes.txt"))
trips = pd.read_csv(os.path.join(gtfs_path, "trips.txt"))
stop_times = pd.read_csv(os.path.join(gtfs_path, "stop_times.txt"))

# Filter out Amtrak Thruway Connecting Service (bus routes)
routes = routes[routes['route_long_name'] != 'Amtrak Thruway Connecting Service']

# Define NEC routes (Northeast Corridor - primary rail routes serving the Northeast)
nec_route_names = [
    'Acela',
    'Northeast Regional',
    'Keystone Service',
    'Amtrak Hartford Line',
    'Empire Service',
    'Vermonter',
    'Adirondack',
    'Carolinian',
    'Palmetto',
    'Silver Meteor',
    'Downeaster'
]

# Filter routes to NEC only
nec_routes = routes[routes['route_long_name'].isin(nec_route_names)]
nec_route_ids = set(nec_routes['route_id'].values)

# Filter trips and stops to NEC
nec_trips = trips[trips['route_id'].isin(nec_route_ids)]
nec_stop_times = stop_times[stop_times['trip_id'].isin(nec_trips['trip_id'].values)]
nec_stops = stops[stops['stop_id'].isin(nec_stop_times['stop_id'].values)]

print("=" * 60)
print("NORTHEAST CORRIDOR (NEC) TRANSIT DATA SUMMARY")
print("=" * 60)
print(f"\n📍 Total Rail Stations: {len(nec_stops)}")
print(f"🚂 Total Routes: {len(nec_routes)}")
print(f"🚆 Total Trains (Trips): {len(nec_trips)}")

print("\n" + "=" * 60)
print("ROUTE DETAILS")
print("=" * 60)
for idx, row in nec_routes.iterrows():
    print(f"{row['route_id']}: {row['route_long_name']}")

print("\n" + "=" * 60)
print("SAMPLE STATIONS")
print("=" * 60)
for idx, row in nec_stops.head(15).iterrows():
    print(f"{row['stop_id']}: {row['stop_name']}")

# Additional analysis: trips per route
print("\n" + "=" * 60)
print("TRIPS PER ROUTE")
print("=" * 60)
trips_per_route = nec_trips.groupby('route_id').size().reset_index(name='trip_count')
for idx, row in trips_per_route.iterrows():
    route_name = nec_routes[nec_routes['route_id'] == row['route_id']]['route_long_name'].values
    if len(route_name) > 0:
        print(f"{row['route_id']} ({route_name[0]}): {row['trip_count']} trips")
