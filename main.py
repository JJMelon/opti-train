# Alby Penney - 2026 EE6130 Convex Optimiztation - Final Project: Train Network Optimization
# Main script to load GTFS data, build the train network graph, set up optimization model, solve problem, visualize resutls

# Gurobi license
import os
import json
from time import perf_counter
os.environ['GRB_LICENSE_FILE'] = '/opt/gurobi/gurobi.lic'  # Update this path to your Gurobi license file

import pyomo.environ as pyo
from pyomo.environ import Constraint, Objective, Var, NonNegativeReals, Binary, SolverFactory, ConstraintList
import numpy as np
from load_network import build_network,  load_gtfs, visualize_network
from mrts_utils import RailNetwork, analyze_network, Train, Junction, Track, Station


def _record_timing(timings, label: str, start_time: float):
    timings.append((label, perf_counter() - start_time))


def _print_timing_summary(timings):
    total = sum(duration for _, duration in timings)
    print("\nTiming summary:")
    for label, duration in timings:
        print(f"  {label:<34} {duration:8.3f}s")
    print(f"  {'total':<34} {total:8.3f}s")


def _parse_clock_time_to_minutes(time_text: str) -> int:
    """Parse a HH:MM clock time string into minutes since midnight."""
    parts = str(time_text).strip().split(':')
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_text!r}")
    first, second = (int(part) for part in parts)
    return first * 60 + second


def _normalize_compulsory_stops(raw_stops):
    """Normalize compulsory stop data to a list of station IDs."""
    if raw_stops is None:
        return []
    if isinstance(raw_stops, str):
        return [stop.strip() for stop in raw_stops.split(';') if stop.strip()]
    return [str(stop).strip() for stop in raw_stops if str(stop).strip()]


def init_trains(filename: str, network: RailNetwork):
    """
    Load trains from a timetable JSON file and attach them to the network.

    Expected JSON format:
    {
      "trains": [
        {
          "train_no": 1,
          "from": "BLG",
          "to": "U",
          "compulsory_stop": ["SL", "AVKY"],
          "t_best": "06:30",
          "t_min": -15,
          "t_max": 15,
          "v_dep": 625,
          "w_max": 5
        }
      ]
    }

    Args:
        filename: Path to a JSON timetable file.
        network: RailNetwork to populate.

    Returns:
        List of Train objects added to network.trains.
    """
    with open(filename, 'r', encoding='utf-8') as f:
        timetable = json.load(f)

    train_rows = timetable.get('trains', timetable if isinstance(timetable, list) else [])
    if not isinstance(train_rows, list):
        raise ValueError("Timetable JSON must contain a 'trains' list or be a list of train rows.")

    # Establish sizing from the network so each Train has a consistent schedule vector length.
    num_blocks = network.get_blocks_count()
    num_time_steps = timetable.get('num_time_steps') if isinstance(timetable, dict) else None
    if not isinstance(num_time_steps, int) or num_time_steps <= 0:
        num_time_steps = 10  # default to 10 minutes

    trains = []
    train_counter = 0
    for row in train_rows:
        train_no = row.get('train_no', row.get('id'))
        if train_no is None:
            raise ValueError(f"Missing train number in timetable row: {row}")

        train = Train(id=train_counter, length=row.get('length', 50), max_speed=row.get('max_speed', 80), num_blocks=num_blocks, num_time_steps=num_time_steps)
        train.initial_station = row.get('from')
        train.destination_station = row.get('to')
        train.compulsory_stops = _normalize_compulsory_stops(row.get('compulsory_stop', row.get('compulsory_stop_at')))
        train.ideal_departure_time = row.get('t_best')
        train.ideal_departure_time_minutes = _parse_clock_time_to_minutes(row['t_best']) if row.get('t_best') is not None else None

        t_min = row.get('t_min', 0)
        t_max = row.get('t_max', 0)
        if train.ideal_departure_time_minutes is not None:
            train.departure_window_minutes = (
                train.ideal_departure_time_minutes + int(t_min),
                train.ideal_departure_time_minutes + int(t_max),
            )
            train.departure_time = train.ideal_departure_time_minutes

        train.departure_profit = float(row.get('v_dep', 0))
        train.profit = train.departure_profit
        train.max_waiting_time = int(row.get('w_max', 5))
        train.timetable_row = dict(row)
        trains.append(train)
        train_counter += 1

    print(f"Initialized {len(trains)} trains from timetable.")
    network.trains = trains
    return trains


def load_amtrak_network(show: bool = True, save_path = None, nec_bbox = None):
    """
    Load Amtrak GTFS (from ./gtfs), build the station graph, extract the
    Northeast Corridor (NEC) subgraph and visualize it.

    Returns: (G, SG) where G is the full station graph (networkx.DiGraph)
             and SG is the NEC subgraph (networkx.DiGraph).
    """
    # Load GTFS tables using helper in load_network.py
    stops, routes, trips, stop_times = load_gtfs()

    # Trips that are known to be stale for the NEC visualization/query logic.
    stale_trips = [
        253806, 253807, 253808, 256343, 256345,
        258807, 258808, 258810, 258811,
        257872, 257873, 257874, 257875, 257877, 257878,
    ]

    trips_before_stale = len(trips)
    trips_filtered_stale = trips[~trips['trip_id'].isin(stale_trips)]
    print(
        f"Filtered stale trips: {trips_before_stale} → {len(trips_filtered_stale)} "
        f"(removed {trips_before_stale - len(trips_filtered_stale)} stale trips)"
    )

    # Filter out Amtrak Thruway bus routes
    routes_filtered = routes[~routes['route_long_name'].str.contains("Amtrak Thruway Connecting Service", na=False)]
    print(f"Filtered routes: {len(routes)} → {len(routes_filtered)} (removed {len(routes) - len(routes_filtered)} bus routes)")
    
    # Filter trips to only those on rail routes
    rail_route_ids = set(routes_filtered['route_id'].unique())
    trips_filtered = trips_filtered_stale[trips_filtered_stale['route_id'].isin(rail_route_ids)]
    print(f"Filtered trips: {len(trips_filtered_stale)} → {len(trips_filtered)}")
    
    # Filter stop_times to only those on rail trips
    rail_trip_ids = set(trips_filtered['trip_id'].unique())
    stop_times_filtered = stop_times[stop_times['trip_id'].isin(rail_trip_ids)]
    print(f"Filtered stop_times: {len(stop_times)} → {len(stop_times_filtered)}")

    # Build directed station graph using filtered data
    G = build_network(stops, routes_filtered, trips_filtered, stop_times_filtered)

    # Default NEC bounding box (latitude, longitude window)
    if nec_bbox is None:
        nec_bbox = dict(lat_min=38.5, lat_max=42.5, lon_min=-75.5, lon_max=-70.5)

    # Select nodes inside bounding box
    nec_nodes = [
        n for n in G.nodes
        if nec_bbox["lat_min"] < float(G.nodes[n]["lat"]) < nec_bbox["lat_max"]
        and nec_bbox["lon_min"] < float(G.nodes[n]["lon"]) < nec_bbox["lon_max"]
    ]

    SG = G.subgraph(nec_nodes).copy()

    # Visualize using existing helper (shows full network and NEC panel)
    try:
        visualize_network(G)
    except Exception:
        # Fallback: try visualizing the NEC subgraph only
        try:
            visualize_network(SG)
        except Exception:
            pass

    return G, SG


def load_test_network(network_name: str) -> RailNetwork:
        network = RailNetwork.from_file(network_name)
        print("\n✓ Network loaded successfully")
        
        # Print network info
        info = network.get_network_info()
        print(f"\nNetwork: {info['name']}")
        print(f"Stations: {info['stations_count']}")
        print(f"Tracks: {info['tracks_count']}")
        print(f"Junctions: {info['junctions_count']}")
        print(f"Total Track Length: {info['total_track_length_km']:.2f} km")
        
        # Validate
        is_valid, errors = network.validate()
        if is_valid:
            print("\n✓ Network validation passed")
        else:
            print("\n✗ Validation errors:")
            for error in errors:
                print(f"  - {error}")
        
        # Analyze
        analysis = analyze_network(network)
        print(f"\nBidirectional Tracks: {analysis['track_statistics']['bidirectional_tracks']}")
        print(f"Average Speed Limit: {analysis['track_statistics']['average_speed_limit']:.1f} km/h")

        return network


if __name__ == "__main__":
    #load_amtrak_network()
    # Load an existing network from GTFS or use a small test network
    network_filename = 'singletrack_swedish_network.json'  # Change to your test network file
    setup_timings = []

    load_network_start = perf_counter()
    try:
        network = load_test_network(network_filename)
    except FileNotFoundError:
        print("\n Test Network not found.")
        exit(1)
    _record_timing(setup_timings, "load network", load_network_start)

    station_map_start = perf_counter()
    # Build station -> block id map
    network.station_to_blocks = network._build_station_to_blocks_map()
    _record_timing(setup_timings, "build station map", station_map_start)
    
    # DEBUG #
    network.DEBUG = True
    # Initialize variables and model objects

    # x^r_ij = 1 if train r is operating on block i and time j, 0 otherwise
    # x^r represents schedule of train r. Binary vector of length M x N where M is number of blocks and N is number of time steps

    
    train_init_start = perf_counter()
    trains = init_trains('ideal_passenger_timetable_morning.json', network)
    _record_timing(setup_timings, "load trains", train_init_start)
    # Scheduling horizon: timesteps in minutes
    N = 60*5 # Number of timesteps (minutes)
    M = network.get_blocks_count() # number of blocks (each 100m of track segment)
    R = len(trains) # number of trains (for testing, set automatically from GTFS data in future)

    model_init_start = perf_counter()
    # Initialize pyomo model
    model = pyo.ConcreteModel()

    # HARDCODED TRAIN PROPERTIES FOR TESTING - TODO: Load from GTFS data in future
    # optimal departure time

    # Define indexed set of trains, blocks, and time steps for pyomo model
    model.R = pyo.RangeSet(0, R-1) # Set of trains
    model.M = pyo.RangeSet(0, M-1) # Set of blocks
    model.N = pyo.RangeSet(0, N-1) # Set of time steps
    model.x = pyo.Var(model.R, model.M, model.N, domain=pyo.Binary)
    _record_timing(setup_timings, "create model", model_init_start)

    variables_start = perf_counter()
    if network.DEBUG:
        print(f"\nModel sets initialized: R={R} trains, M={M} blocks, N={N} time steps, total binary variables: {R*M*N}")
        print("Initializing train schedule variables (x^r_ij)...", end="")
    # Initialize train schedules, assign initial values to x^r_ij variables
    for train in network.trains:
        for i in range(M):
            for j in range(N):
                model.x[train.id, i, j].value = 0  # Start with all variables set to 0 (no trains scheduled)
    if network.DEBUG:
        print("done!")
    _record_timing(setup_timings, "initialize variables", variables_start)

    ############################## Optimization model constraints ##########################

    # Visualize network and trains:
    network.visualize_network(trains=None, show=True, save_path="network_visualization.png", flip_axes=True, label_track_blocks=True)

    print("\nSetting up optimization model constraints...", end="")
    ############### NETWORK LINKING CONSTRAINTS ###############
    # Block occupancy constraints: For each block, ensure that at most one train occupies it at any time step
    block_occupancy_start = perf_counter()
    model.block_occupancy = ConstraintList()
    for i in range(M):
        for j in range(N):
            model.block_occupancy.add(sum(model.x[r, i, j] for r in model.R) <= 1)
    _record_timing(setup_timings, "block occupancy constraints", block_occupancy_start)
    
    ############### INDIVIDUAL TRAIN SCHEDULING CONSTRAINTS ###############
    # Train movement constraints: Ensure that if a train is on block i at time j, it can only be on adjacent blocks at time j+1 (or stay on the same block if it hasn't moved yet)
    train_movement_start = perf_counter()
    adjacent_blocks_by_block = [network.get_adjacent_blocks(i) for i in range(M)]
    model.train_movement_constraint = ConstraintList()
    for r in model.R:
        for i in range(M): # loop over blocks
            adjacent_blocks = adjacent_blocks_by_block[i]
            for j in range(N-1):  # Up to N-1 since we look at j+1
                model.train_movement_constraint.add(
                    model.x[r, i, j] <= sum(model.x[r,  adj, j+1] for adj in adjacent_blocks) + model.x[r, i, j+1]
                )
    _record_timing(setup_timings, "train movement constraints", train_movement_start)
    # Train single block constraint: for each train, ensure it occupies at most one block at a time
    single_block_start = perf_counter()
    model.single_block_constraint = ConstraintList()
    for r in model.R:
        for j in range(N):
            model.single_block_constraint.add(sum(model.x[r, i, j] for i in model.M) <= 1)
    _record_timing(setup_timings, "single block constraints", single_block_start)

    # Train compulsory stop constraints: Ensure that trains stop at their compulsory stations for 1 min (for testing, set station blocks and compulsory stops manually, load from GTFS in future)
    compulsory_stop_start = perf_counter()
    model.compulsory_stop_constraints = ConstraintList()
    for train in network.trains:
        for stop in train.compulsory_stops:
            stop_blocks = network.station_to_blocks.get(stop, [])
            if not stop_blocks:
                print(f"Error: No blocks found for compulsory stop {stop} of train {train.id}")
                exit(1)
            # For testing, require the train to occupy at least one of the stop blocks for at least 1 minute.
            model.compulsory_stop_constraints.add(sum(model.x[train.id, block, j] for block in stop_blocks for j in range(N)) >= 1)
    _record_timing(setup_timings, "compulsory stop constraints", compulsory_stop_start)

    # Train departure constraints: Ensure that trains start schedule at their initial block
    departure_constraints_start = perf_counter()
    model.departure_constraints = ConstraintList()
    for train in network.trains:
        initial_blocks = network.station_to_blocks.get(train.initial_station, [])
        if not initial_blocks:
            print(f"Error: No blocks found for initial station {train.initial_station} of train {train.id}")
            exit(1)
        model.departure_constraints.add(sum(model.x[train.id, block, 0] for block in initial_blocks) == 1)
    _record_timing(setup_timings, "departure constraints", departure_constraints_start)

    # Train arrival constraints: Ensure that trains end schedule at their destination block (for testing, set destination as last block M-1)
    # TODO: load actual destination blocks from GTFS data in future
    # TODO: enable multi-track networks where trains can arrive at different blocks depending on routing decisions
    arrival_constraints_start = perf_counter()
    model.arrival_constraints = ConstraintList()
    for train in network.trains:
        end_blocks = network.station_to_blocks.get(train.destination_station, [])
        if not end_blocks:
            print(f"Error: No blocks found for destination station {train.destination_station} of train {train.id}")
            exit(1)
        model.arrival_constraints.add(sum(model.x[train.id, block, N-1] for block in end_blocks) == 1)
    _record_timing(setup_timings, "arrival constraints", arrival_constraints_start)

    
    ###################### STATION OCCUPANCY CONSTRAINTS ###################### 
    # For each station, ensure that the number of trains occupying blocks associated with that station at any time step does not exceed the station's capacity.
    station_capacity_start = perf_counter()
    for station in network.stations.values():
        station_blocks = network.station_to_blocks.get(station.id, [])
        if not station_blocks:
            print(f"Warning: No blocks found for station {station.id} ({station.name})")
            continue
        model.add_component(
            f'station_capacity_{station.id}',
            ConstraintList()
        )
        for j in range(N):
            model.component(f'station_capacity_{station.id}').add(
                sum(model.x[r, block, j] for r in model.R for block in station_blocks) <= station.capacity
            )
    print("done!")
    _record_timing(setup_timings, "station capacity constraints", station_capacity_start)
    if network.DEBUG:
        print("\nConstraint Counts:")
        print(f"Block occupancy constraints: {len(model.block_occupancy)}")
        print(f"Train movement constraints: {len(model.train_movement_constraint)}")
        print(f"Single block constraints: {len(model.single_block_constraint)}")
        print(f"Station capacity constraints: {sum(len(model.component(f'station_capacity_{station.id}')) for station in network.stations.values())}")
   
   
    #################### OBJECTIVE #######################
    # Define objective function 
    objective_start = perf_counter()
    model.obj = Objective(
        expr = sum(train.get_profit(model, network) for train in network.trains),
        sense = pyo.maximize
    )
    _record_timing(setup_timings, "build objective", objective_start)

    solve_start = perf_counter()
    #model.obj.pprint()

    # Solve the optimization problem
    solver = SolverFactory('gurobi')
    results = solver.solve(model, tee=True)
    _record_timing(setup_timings, "solve model", solve_start)

    # Visualize and analyze results 
    # Extract train schedules from model variables
    extract_start = perf_counter()
    for train in network.trains:
        train.schedule = np.zeros((M, N), dtype=int)
        for i in range(M):
            for j in range(N):
                train.schedule[i, j] = pyo.value(model.x[train.id, i, j])

    # Print train schedules in a readable format
    for train in network.trains:
        print(f"\nTrain {train.id} Schedule:")
        for j in range(N):
            occupied_blocks = [i for i in range(M) if train.schedule[i, j] == 1]
            #print(f"Time {j}: Blocks {occupied_blocks}")
    _record_timing(setup_timings, "extract schedules", extract_start)

    _print_timing_summary(setup_timings)

    # Print a crude visual of the track 