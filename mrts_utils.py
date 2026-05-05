"""
Multi-Track Rail Network Standard (MRTS) v1.0 - Python Utilities

This module provides utilities for parsing, validating, and working with
multi-track rail networks in the MRTS format.
"""

import json
import jsonschema
from typing import Dict, List, Tuple, Optional, Set, Union
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pyomo.environ as pyo



@dataclass
class Coordinate:
    """Represents a geographic coordinate."""
    lat: float
    lon: float
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Coordinate':
        return cls(lat=data['lat'], lon=data['lon'])


@dataclass
class Station:
    """Represents a railway station with aggregate capacity."""
    id: str
    name: str
    coordinates: Coordinate
    type: str
    capacity: int
    dwell_time_seconds: int
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Station':
        return cls(
            id=data['id'],
            name=data['name'],
            coordinates=Coordinate.from_dict(data['coordinates']),
            type=data['type'],
            capacity=data.get('capacity', 1),
            dwell_time_seconds=data.get('dwell_time_seconds', 0)
        )


@dataclass
class Track:
    """Represents a railway track segment."""
    id: str
    name: str
    from_id: str
    to_id: str
    type: str
    length_meters: float
    speed_limit_kmh: int
    capacity: int
    bidirectional: bool
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Track':
        return cls(
            id=data['id'],
            name=data['name'],
            from_id=data['from_id'],
            to_id=data['to_id'],
            type=data['type'],
            length_meters=data['length_meters'],
            speed_limit_kmh=data['properties'].get('speed_limit_kmh', 0),
            capacity=data['capacity'].get('max_trains', 1),
            bidirectional=data['properties'].get('bidirectional', False)
        )


@dataclass
class Junction:
    """Represents a railway junction."""
    id: str
    name: str
    coordinates: Coordinate
    connected_tracks: List[Tuple[str, str]]  # (track_id, direction)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Junction':
        tracks = [(t['track_id'], t['direction']) for t in data['connected_tracks']]
        return cls(
            id=data['id'],
            name=data['name'],
            coordinates=Coordinate.from_dict(data['coordinates']),
            connected_tracks=tracks
        )


class RailNetwork:
    """Main class for working with multi-track rail networks."""
    
    def __init__(self, network_data: Dict):
        """Initialize a rail network from parsed JSON data."""
        self.data = network_data
        self.network = network_data['network']
        self.metadata = network_data['metadata']
        self.stations = {s['id']: Station.from_dict(s) for s in network_data.get('stations', [])}
        self.tracks = {t['id']: Track.from_dict(t) for t in network_data.get('tracks', [])}
        self.junctions = {j['id']: Junction.from_dict(j) for j in network_data.get('junctions', [])}
        self.side_tracks = network_data.get('side_tracks', [])
        self.constraints = network_data.get('constraints', [])
        self.trains = []  # List of Train objects, to be populated from GTFS data or defined manually for testing
        self._block_to_track_mapping = None  # Cache for block-to-track mapping (lazy initialization)
        self._adjacent_blocks_mapping = None  # Cache for block adjacency mapping (lazy initialization)
    
    @classmethod
    def from_file(cls, filepath: str) -> 'RailNetwork':
        """Load a rail network from a JSON file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls(data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'RailNetwork':
        """Load a rail network from a JSON string."""
        data = json.loads(json_str)
        return cls(data)

    def validate(self, schema_path: Optional[str] = None) -> Tuple[bool, List[str]]:
        """
        Validate the network against JSON schema.
        
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        # Basic structure validation
        if 'network' not in self.data:
            errors.append("Missing 'network' section")
        if 'stations' not in self.data:
            errors.append("Missing 'stations' section")
        if 'tracks' not in self.data:
            errors.append("Missing 'tracks' section")
        if 'junctions' not in self.data:
            errors.append("Missing 'junctions' section")
        
        # Referential integrity checks
        errors.extend(self._check_referential_integrity())
        
        return len(errors) == 0, errors
    
    def _check_referential_integrity(self) -> List[str]:
        """Check that all references are valid."""
        errors = []
        station_ids = set(self.stations.keys())
        track_ids = set(self.tracks.keys())
        
        # Check track references
        for track_id, track_data in self.data['tracks'].items() if isinstance(self.data['tracks'], dict) else enumerate(self.data['tracks']):
            track = track_data
            if track['from_id'] not in station_ids:
                errors.append(f"Track {track['id']}: Invalid from_id '{track['from_id']}'")
            if track['to_id'] not in station_ids:
                errors.append(f"Track {track['id']}: Invalid to_id '{track['to_id']}'")
        
        # Check junction track connections
        for junction_id, junction in self.junctions.items():
            for track_id, direction in junction.connected_tracks:
                if track_id not in track_ids:
                    errors.append(f"Junction {junction_id}: Invalid track connection '{track_id}'")
        
        return errors

    def get_blocks_count(self) -> int:
        """
        Calculate total number of blocks in the network.
        Includes both track blocks and station capacity blocks.
        Each simultaneous train slot at a station counts as one block.
        """
        block_length_meters = 100
        
        # Count track blocks
        total_track_length = sum(track.length_meters for track in self.tracks.values())
        track_blocks = int(total_track_length / block_length_meters)
        
        # Count station capacity blocks (one block per simultaneous train slot)
        station_blocks = sum(station.capacity for station in self.stations.values())
        
        return track_blocks + station_blocks
    
    def _build_block_to_track_mapping(self) -> Dict[int, Tuple]:
        """
        Build a mapping from global block index to block information.
        
        Returns:
            Dictionary where key is global block index and value is tuple:
            - For track blocks: ('track', track_id, position_on_track)
            - For station blocks: ('station', station_id, capacity_position)
            
        Track blocks are indexed first (sorted by track ID), then station blocks (sorted by station ID).
        """
        block_length_meters = 100
        block_mapping = {}
        global_block_index = 0
        
        # First, add all track blocks (sorted by track ID for consistency)
        for track_id in sorted(self.tracks.keys()):
            track = self.tracks[track_id]
            num_blocks_on_track = int(track.length_meters / block_length_meters)
            
            for position_on_track in range(num_blocks_on_track):
                block_mapping[global_block_index] = ('track', track_id, position_on_track)
                global_block_index += 1
        
        # Then, add all station blocks (sorted by station ID for consistency)
        for station_id in sorted(self.stations.keys()):
            station = self.stations[station_id]
            for capacity_position in range(station.capacity):
                block_mapping[global_block_index] = ('station', station_id, capacity_position)
                global_block_index += 1
        
        return block_mapping
    
    def _get_block_to_track_mapping(self) -> Dict[int, Tuple]:
        """Get the block mapping, building it if necessary (lazy initialization)."""
        if self._block_to_track_mapping is None:
            self._block_to_track_mapping = self._build_block_to_track_mapping()
        return self._block_to_track_mapping

    def _build_adjacent_blocks_mapping(self) -> Dict[int, List[int]]:
        """
        Build a cached map from each block index to its adjacent block indices.

        This avoids recomputing adjacency with repeated linear scans while building
        movement constraints.
        """
        block_mapping = self._get_block_to_track_mapping()
        track_blocks_by_position: Dict[Tuple[str, int], int] = {}
        station_blocks_by_id: Dict[str, List[int]] = {}
        track_ids_by_station: Dict[str, List[str]] = {}

        for block_idx, info in block_mapping.items():
            if info[0] == 'track':
                _, track_id, position_on_track = info
                track_blocks_by_position[(track_id, position_on_track)] = block_idx
                track = self.tracks[track_id]
                track_ids_by_station.setdefault(track.from_id, []).append(track_id)
                track_ids_by_station.setdefault(track.to_id, []).append(track_id)
            else:
                _, station_id, _ = info
                station_blocks_by_id.setdefault(station_id, []).append(block_idx)

        adjacent_blocks_by_block: Dict[int, List[int]] = {}

        for block_idx, info in block_mapping.items():
            adjacent_blocks: List[int] = []
            seen = set()

            def add_adjacent(candidate: Optional[int]) -> None:
                if candidate is not None and candidate != block_idx and candidate not in seen:
                    seen.add(candidate)
                    adjacent_blocks.append(candidate)

            if info[0] == 'track':
                _, track_id, position_on_track = info
                track = self.tracks[track_id]
                block_length_meters = 100
                num_blocks_on_track = int(track.length_meters / block_length_meters)

                add_adjacent(track_blocks_by_position.get((track_id, position_on_track - 1)))
                add_adjacent(track_blocks_by_position.get((track_id, position_on_track + 1)))

                if position_on_track == 0:
                    for station_block in station_blocks_by_id.get(track.from_id, []):
                        add_adjacent(station_block)

                if position_on_track == num_blocks_on_track - 1:
                    for station_block in station_blocks_by_id.get(track.to_id, []):
                        add_adjacent(station_block)

            elif info[0] == 'station':
                _, station_id, _ = info
                for station_block in station_blocks_by_id.get(station_id, []):
                    add_adjacent(station_block)

                for track_id in track_ids_by_station.get(station_id, []):
                    track = self.tracks[track_id]
                    block_length_meters = 100
                    num_blocks_on_track = int(track.length_meters / block_length_meters)

                    if track.from_id == station_id:
                        add_adjacent(track_blocks_by_position.get((track_id, 0)))

                    if track.to_id == station_id:
                        add_adjacent(track_blocks_by_position.get((track_id, num_blocks_on_track - 1)))

            adjacent_blocks_by_block[block_idx] = adjacent_blocks

        return adjacent_blocks_by_block

    def _get_adjacent_blocks_mapping(self) -> Dict[int, List[int]]:
        """Get the adjacency mapping, building it if necessary (lazy initialization)."""
        if self._adjacent_blocks_mapping is None:
            self._adjacent_blocks_mapping = self._build_adjacent_blocks_mapping()
        return self._adjacent_blocks_mapping
    
    def get_adjacent_blocks(self, block_index: int) -> List[int]:
        """
        Get the indices of blocks adjacent to the given block.
        
        Supports multiple unrelated tracks and station capacity blocks.
        Adjacent blocks are:
        - For track blocks: previous/next blocks on same track, or station blocks if at track end
        - For station blocks: all other blocks in the same station, or track blocks if at station edge
        
        Args:
            block_index: Global block index (0 to M-1)
            
        Returns:
            List of adjacent block indices
        """
        return list(self._get_adjacent_blocks_mapping().get(block_index, []))
    
    def _get_station_blocks(self, station_id: str, block_mapping: Dict[int, Tuple]) -> List[int]:
        """Get all block indices for blocks in a given station."""
        station_blocks = []
        for block_idx, info in block_mapping.items():
            if info[0] == 'station' and info[1] == station_id:
                station_blocks.append(block_idx)
        return station_blocks
    
    def _get_connected_track_ids(self, station_id: str) -> List[str]:
        """Get all track IDs connected to a station."""
        connected_track_ids = []
        for track_id, track in self.tracks.items():
            if track.from_id == station_id or track.to_id == station_id:
                connected_track_ids.append(track_id)
        return connected_track_ids
    
    def _get_blocks_for_station(self, station_id: str) -> Set[int]:
        """
        Get all block indices that belong to a specific station.
        
        Args:
            station_id: Station ID
            
        Returns:
            Set of block indices belonging to the station
        """
        block_mapping = self._get_block_to_track_mapping()
        station_blocks = set()
        for block_idx, info in block_mapping.items():
            if info[0] == 'station' and info[1] == station_id:
                station_blocks.add(block_idx)
        return station_blocks
    
    def _build_station_to_blocks_map(self) -> Dict[str, Set[int]]:
        """
        Build a map from station ID to set of block indices in that station.
        Caches result for efficient repeated access.
        
        Returns:
            Dictionary mapping station_id -> Set[block_indices]
        """
        if not hasattr(self, '_station_to_blocks_map_cache'):
            self._station_to_blocks_map_cache = {}
            for station_id in self.stations.keys():
                self._station_to_blocks_map_cache[station_id] = self._get_blocks_for_station(station_id)
        return self._station_to_blocks_map_cache
    
    def compute_fastest_travel_time(self, initial_station_id: str, destination_station_id: str) -> Optional[int]:
        """
        Compute the fastest travel time (in timesteps) for a train to travel from an initial station
        to a destination station, without considering other trains.
        
        Uses BFS (Breadth-First Search) on the block adjacency graph to find the shortest path.
        Each block transition takes 1 timestep. Train starts in any block of the initial station
        and must reach any block in the destination station.
        
        Args:
            initial_station_id: Station ID where the train starts
            destination_station_id: Station ID of the destination
            
        Returns:
            Travel time in timesteps (number of blocks to traverse), or None if destination is unreachable
        """
        from collections import deque
        
        # Validate stations exist
        if initial_station_id not in self.stations:
            return None
        
        if destination_station_id not in self.stations:
            return None
        
        # Get blocks for both stations using cached map
        station_to_blocks = self._build_station_to_blocks_map()
        initial_blocks = station_to_blocks[initial_station_id]
        destination_blocks = station_to_blocks[destination_station_id]
        
        # If either station has no blocks, it's invalid
        if not initial_blocks or not destination_blocks:
            return None
        
        # If stations are the same, travel time is 0
        if initial_station_id == destination_station_id:
            return 0
        
        # BFS from all initial station blocks to any destination block
        queue = deque([(block, 0) for block in initial_blocks])  # (block_index, distance)
        visited = set(initial_blocks)
        
        while queue:
            current_block, distance = queue.popleft()
            
            # Get adjacent blocks
            adjacent = self.get_adjacent_blocks(current_block)
            
            for next_block in adjacent:
                if next_block in destination_blocks:
                    # Found destination
                    return distance + 1
                
                if next_block not in visited:
                    visited.add(next_block)
                    queue.append((next_block, distance + 1))
        
        # Destination unreachable
        return None
    
    def compute_travel_time_in_schedule(self, model: pyo.ConcreteModel, train_id: int, 
                                       initial_station_id: str, destination_station_id: str) -> pyo.Expression:
        """
        Compute a Pyomo expression for the actual travel time of a train in the schedule.
        
        The travel time is measured as the difference between the (weighted) timestep when the train
        is in the destination station and when it is in the initial station. This is formulated as
        a linear Pyomo expression suitable for use in objectives and constraints.
        
        The expression computes:
          travel_time = sum(j * indicator[train occupies destination at j]) 
                      - sum(j * indicator[train occupies initial at j])
        
        where indicator[train occupies station at j] = 1 if sum(x[train_id, i, j] for i in station_blocks) > 0
        
        Args:
            model: Pyomo ConcreteModel with decision variables x[r, i, j]
                   where x[r, i, j] = 1 if train r occupies block i at timestep j
            train_id: Train ID (should match indices in model.x)
            initial_station_id: Station ID where train departs from
            destination_station_id: Station ID where train arrives
            
        Returns:
            A Pyomo expression representing the travel time that can be used in the objective
            function or constraints. Smaller values mean trains travel faster.
            
        Example:
            travel_expr = network.compute_travel_time_in_schedule(
                model, train_id=0, 
                initial_station_id='A', 
                destination_station_id='B'
            )
            model.obj = pyo.Objective(expr=travel_expr, sense=pyo.minimize)
        """
        initial_blocks = list(self._build_station_to_blocks_map()[initial_station_id])
        dest_blocks = list(self._build_station_to_blocks_map()[destination_station_id])
        
        # Build expression by explicitly looping over timesteps and blocks
        time_in_dest = 0
        time_in_initial = 0
        
        for j in model.N: # loop across timesteps
            # Sum occupancy across destination blocks at timestep j
            dest_occupancy = sum(model.x[train_id, i, j] for i in dest_blocks) # Indicator of whether train is in destination at time j
            time_in_dest += j * dest_occupancy
            
            # Sum occupancy across initial blocks at timestep j
            init_occupancy = sum(model.x[train_id, i, j] for i in initial_blocks) # Indicator of whether train is in initial station at time j
            time_in_initial += j * init_occupancy
        
        # Travel time = total time - time in destination - time in initial
        travel_time = len(model.N) - time_in_dest - time_in_initial
        
        return travel_time

    def get_network_info(self) -> Dict:
        """Get summary information about the network."""
        return {
            'id': self.network['id'],
            'name': self.network['name'],
            'description': self.network.get('description', ''),
            'stations_count': len(self.stations),
            'tracks_count': len(self.tracks),
            'junctions_count': len(self.junctions),
            'side_tracks_count': len(self.side_tracks),
            'total_track_length_km': sum(t.length_meters for t in self.tracks.values()) / 1000,
            'station_capacity_total': sum(s.capacity for s in self.stations.values())
        }
    
    def get_connected_tracks(self, station_id: str) -> List[str]:
        """Get all tracks connected to a station."""
        if station_id not in self.stations:
            return []
        
        connected = set()
        for track_id, track in self.tracks.items():
            if track.from_id == station_id or track.to_id == station_id:
                connected.add(track_id)
        return list(connected)
    
    def get_path(self, from_station_id: str, to_station_id: str) -> Optional[List[str]]:
        """
        Find a path between two stations using BFS.
        Returns list of station IDs from source to destination.
        """
        if from_station_id not in self.stations or to_station_id not in self.stations:
            return None
        
        from collections import deque
        
        queue = deque([(from_station_id, [from_station_id])])
        visited = {from_station_id}
        
        while queue:
            current, path = queue.popleft()
            
            if current == to_station_id:
                return path
            
            # Find all tracks from current station
            connected = self.get_connected_tracks(current)
            next_stations = set()
            
            for track_id in connected:
                track = self.tracks.get(track_id)
                if track:
                    if track.from_id == current:
                        next_stations.add(track.to_id)
                    elif track.bidirectional and track.to_id == current:
                        next_stations.add(track.from_id)
            
            for next_station in next_stations:
                if next_station not in visited:
                    visited.add(next_station)
                    queue.append((next_station, path + [next_station]))
        
        return None

    def visualize_network(self, trains: Optional[List] = None, show: bool = True, save_path: Optional[str] = None, flip_axes: bool = False, label_track_blocks: bool = False):
        """
        Visualize the rail network graph with stations, tracks, and optional train routes.

        Stations are drawn at their geographic coordinates. Tracks are drawn as directed
        arrows, and each train route is overlaid in a distinct color.

        Args:
            trains: Optional list of train-like objects or dictionaries. If omitted,
                the method uses ``self.trains``.
            show: If True, display the figure with ``plt.show()``.
            save_path: Optional path to save the rendered figure.
            flip_axes: If True, swap latitude and longitude axes (lat on x-axis, lon on y-axis).
                Default is False (lon on x-axis, lat on y-axis).
            label_track_blocks: If True, mark and label individual track blocks along edges.
                Default is False.

        Returns:
            The matplotlib figure and axes objects.
        """
        try:
            import matplotlib.cm as cm
            import matplotlib.pyplot as plt
            import networkx as nx
            from matplotlib.lines import Line2D
        except ImportError as exc:
            raise ImportError(
                "RailNetwork.visualize_network requires matplotlib and networkx"
            ) from exc

        graph = nx.DiGraph()
        positions = {}

        for station in self.stations.values():
            graph.add_node(
                station.id,
                name=station.name,
                lat=station.coordinates.lat,
                lon=station.coordinates.lon,
                type=station.type,
            )
            if flip_axes:
                positions[station.id] = (station.coordinates.lat, station.coordinates.lon)
            else:
                positions[station.id] = (station.coordinates.lon, station.coordinates.lat)

        for track in self.tracks.values():
            graph.add_edge(
                track.from_id,
                track.to_id,
                track_id=track.id,
                name=track.name,
                bidirectional=track.bidirectional,
            )
            if track.bidirectional:
                graph.add_edge(
                    track.to_id,
                    track.from_id,
                    track_id=track.id,
                    name=track.name,
                    bidirectional=track.bidirectional,
                )

        fig, ax = plt.subplots(figsize=(12, 9))
        ax.set_title(
            f"{self.network.get('name', 'Rail Network')} - Network Graph",
            fontsize=14,
            fontweight="bold",
        )
        ax.set_facecolor("#f7f8fb")

        base_edges = list(graph.edges())
        if base_edges:
            nx.draw_networkx_edges(
                graph,
                positions,
                edgelist=base_edges,
                edge_color="#9aa4b2",
                width=1.4,
                arrows=True,
                arrowsize=14,
                alpha=0.45,
                ax=ax,
                connectionstyle="arc3,rad=0.0",
            )

        station_order = list(graph.nodes())
        station_colors = []
        station_sizes = []
        station_to_blocks = self._build_station_to_blocks_map()

        def format_block_ids(block_ids: Set[int]) -> str:
            if not block_ids:
                return "none"
            return ", ".join(str(block_id) for block_id in sorted(block_ids))

        for station_id in station_order:
            station = self.stations[station_id]
            if station.type == "terminal":
                station_colors.append("#1565c0")
                station_sizes.append(460)
            elif station.type == "junction_station":
                station_colors.append("#ef6c00")
                station_sizes.append(420)
            else:
                station_colors.append("#2e7d32")
                station_sizes.append(360)

        if station_order:
            station_labels = {
                station_id: f"{self.stations[station_id].name}\nBlocks: {format_block_ids(station_to_blocks.get(station_id, set()))}"
                for station_id in station_order
            }
            center_x = sum(positions[station_id][0] for station_id in station_order) / len(station_order)
            center_y = sum(positions[station_id][1] for station_id in station_order) / len(station_order)
            nx.draw_networkx_nodes(
                graph,
                positions,
                nodelist=station_order,
                node_color=station_colors,
                node_size=station_sizes,
                edgecolors="#ffffff",
                linewidths=2,
                ax=ax,
            )
            for station_id in station_order:
                label_x, label_y = positions[station_id]
                offset_x = 10 if label_x <= center_x else -10
                offset_y = 12 if label_y <= center_y else -12
                ax.annotate(
                    station_labels[station_id],
                    xy=(label_x, label_y),
                    xytext=(offset_x, offset_y),
                    textcoords="offset points",
                    fontsize=14,
                    fontweight="bold",
                    color="#111827",
                    ha="left" if offset_x > 0 else "right",
                    va="bottom" if offset_y > 0 else "top",
                    zorder=6,
                )

        route_trains = self.trains if trains is None else trains
        # Group routes by path (tuple) to detect overlapping routes
        routes_by_path = {}
        for index, train in enumerate(route_trains):
            if isinstance(train, dict):
                train_id = train.get("id", index)
                train_name = train.get("name", f"Train {train_id}")
                explicit_path = train.get("station_path") or train.get("route") or train.get("path")
                start_station = train.get("initial_station")
                end_station = train.get("destination_station")
            else:
                train_id = getattr(train, "id", index)
                train_name = getattr(train, "name", f"Train {train_id}")
                explicit_path = getattr(train, "station_path", None) or getattr(train, "route", None) or getattr(train, "path", None)
                start_station = getattr(train, "initial_station", None)
                end_station = getattr(train, "destination_station", None)

            path = list(explicit_path) if isinstance(explicit_path, (list, tuple)) else None
            if path is None and start_station and end_station:
                path = self.get_path(start_station, end_station)

            if path and len(path) > 1 and all(station_id in self.stations for station_id in path):
                path_tuple = tuple(path)
                if path_tuple not in routes_by_path:
                    routes_by_path[path_tuple] = []
                routes_by_path[path_tuple].append(str(train_name))

        route_handles = []
        if routes_by_path:
            route_cmap = cm.get_cmap("tab10", max(1, len(routes_by_path)))
            for route_index, (path_tuple, train_names) in enumerate(routes_by_path.items()):
                path = list(path_tuple)
                edges = list(zip(path[:-1], path[1:]))
                color = route_cmap(route_index)
                nx.draw_networkx_edges(
                    graph,
                    positions,
                    edgelist=edges,
                    edge_color=[color],
                    width=3.2,
                    arrows=True,
                    arrowsize=20,
                    alpha=0.95,
                    ax=ax,
                    connectionstyle="arc3,rad=0.08",
                )
                # Combine all train names for routes that share the same path
                combined_label = " / ".join(train_names)
                route_handles.append(
                    Line2D([0], [0], color=color, lw=3.2, label=combined_label)
                )

        station_handles = [
            Line2D([0], [0], marker="o", color="w", label="Terminal station", markerfacecolor="#1565c0", markersize=10),
            Line2D([0], [0], marker="o", color="w", label="Junction station", markerfacecolor="#ef6c00", markersize=10),
            Line2D([0], [0], marker="o", color="w", label="Intermediate station", markerfacecolor="#2e7d32", markersize=10),
        ]

        legend_handles = station_handles + route_handles
        if legend_handles:
            ax.legend(handles=legend_handles, loc="upper left", fontsize=14, frameon=True)

        # Mark and label track blocks if requested
        if label_track_blocks:
            block_mapping = self._get_block_to_track_mapping()
            block_length_meters = 100

            for track_id, track in self.tracks.items():
                from_pos = positions[track.from_id]
                to_pos = positions[track.to_id]
                num_blocks_on_track = int(track.length_meters / block_length_meters)

                if num_blocks_on_track > 0:
                    # Draw marks and labels at each block position along the track
                    for block_num in range(num_blocks_on_track):
                        # Interpolate position between from_pos and to_pos
                        fraction = (block_num + 0.5) / num_blocks_on_track
                        mark_x = from_pos[0] + fraction * (to_pos[0] - from_pos[0])
                        mark_y = from_pos[1] + fraction * (to_pos[1] - from_pos[1])

                        # Find the block ID for this position
                        block_id = None
                        for bid, info in block_mapping.items():
                            if info[0] == 'track' and info[1] == track_id and info[2] == block_num:
                                block_id = bid
                                break

                        # Draw small mark
                        ax.plot(mark_x, mark_y, '+', color='#666666', markersize=6, alpha=0.75, zorder=5)

                        # Draw label if block was found
                        if block_id is not None:
                            ax.annotate("Block " +str(block_id), xy=(mark_x, mark_y), xytext=(0, 6), 
                                       textcoords='offset points', fontsize=10, ha='center', va='bottom', 
                                       alpha=1, zorder=6)

        if flip_axes:
            ax.set_xlabel("Latitude")
            ax.set_ylabel("Longitude")
        else:
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, alpha=0.2, linewidth=0.6)
        ax.margins(0.15)  # Add 15% buffer space around the edges

        plt.tight_layout()

        if save_path:
            fig.savefig(str(save_path), dpi=150, bbox_inches="tight")

        if show:
            plt.show()

        return fig, ax
    
    def get_track_info(self, track_id: str) -> Optional[Dict]:
        """Get detailed information about a track."""
        if track_id not in self.tracks:
            return None
        
        track_data = self.data['tracks']
        if isinstance(track_data, list):
            track_dict = next((t for t in track_data if t['id'] == track_id), None)
        else:
            track_dict = track_data.get(track_id)
        
        if not track_dict:
            return None
        
        track = self.tracks[track_id]
        return {
            'id': track.id,
            'name': track.name,
            'from': track.from_id,
            'to': track.to_id,
            'type': track.type,
            'length_km': track.length_meters / 1000,
            'speed_limit_kmh': track.speed_limit_kmh,
            'capacity': track.capacity,
            'bidirectional': track.bidirectional
        }
    
    def to_dict(self) -> Dict:
        """Convert network back to dictionary."""
        return self.data
    
    def to_json(self, indent: int = 2) -> str:
        """Convert network to JSON string."""
        return json.dumps(self.data, indent=indent)
    
    def save(self, filepath: str):
        """Save network to a JSON file."""
        with open(filepath, 'w') as f:
            json.dump(self.data, f, indent=2)


class NetworkValidator:
    """Validate networks against JSON schema."""
    
    def __init__(self, schema_path: str):
        """Initialize validator with schema file."""
        with open(schema_path, 'r') as f:
            self.schema = json.load(f)
    
    def validate(self, network_data: Dict) -> Tuple[bool, List[str]]:
        """
        Validate network data against schema. Also ensures each track has length in m that is multiple of 100m for block modeling.
        
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        try:
            jsonschema.validate(instance=network_data, schema=self.schema)
        except jsonschema.ValidationError as e:
            errors.append(f"Schema validation error: {e.message}")
        except jsonschema.SchemaError as e:
            errors.append(f"Schema error: {e.message}")
        
        # Check if each track has length in m that is multiple of 100m for block modeling
        for track_id, track_data in network_data.get('tracks', {}).items():
            length_meters = track_data.get('length_meters', 0)
            if length_meters % 100 != 0:
                errors.append(f"Track {track_id} has length {length_meters} m, which is not a multiple of 100 m.")

        return len(errors) == 0, errors


def analyze_network(network: RailNetwork) -> Dict:
    """Perform comprehensive analysis of a network."""
    analysis = {
        'network_info': network.get_network_info(),
        'track_statistics': {
            'total_tracks': len(network.tracks),
            'bidirectional_tracks': sum(1 for t in network.tracks.values() if t.bidirectional),
            'main_line_tracks': sum(1 for t in network.tracks.values() if t.type == 'main'),
            'total_capacity': sum(t.capacity for t in network.tracks.values()),
            'average_speed_limit': sum(t.speed_limit_kmh for t in network.tracks.values()) / len(network.tracks) if network.tracks else 0
        },
        'junction_statistics': {
            'total_junctions': len(network.junctions)
        },
        'station_statistics': {
            'total_stations': len(network.stations),
            'terminals': sum(1 for s in network.stations.values() if s.type == 'terminal'),
            'intermediate': sum(1 for s in network.stations.values() if s.type == 'intermediate'),
            'junction_stations': sum(1 for s in network.stations.values() if s.type == 'junction_station'),
            'total_station_capacity': sum(s.capacity for s in network.stations.values())
        }
    }
    return analysis


if __name__ == '__main__':
    # Example usage
    print("Multi-Track Rail Network Standard (MRTS) - Python Utilities")
    print("=" * 60)
    
    # Load example network
    try:
        network = RailNetwork.from_file('example_network.json')
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
        
    except FileNotFoundError:
        print("example_network.json not found")

class Train:
    """Represents a train with specific characteristics. Used for scheduling and optimization, assigned the x^r_ij variables"""
    
    def __init__(self, id: int, length: int, max_speed: int, num_blocks: int, num_time_steps: int):
        '''
        Arguments:
            id (int): Unique identifier for the train
            length (int): Length of the train in meters
            max_speed (int): Maximum speed of the train in km/h
            num_blocks (int): Total number of blocks in the network (for schedule variable length)
            num_time_steps (int): Total number of time steps in the scheduling horizon (for schedule variable length)
        '''
        self.id = id
        self.length = length
        self.max_speed = max_speed
        self.schedule_length = num_blocks * num_time_steps  # Total number of x^r_ij variables for this train
        self.departure_time: Union[float, None] = None  # Assigned later
        self.profit = 0 # assigned later
        self.max_waiting_time = 5 # minutes, for delay penalty in profit calculation
        self.destination_station: Union[str, None] = None # assigned later
        self.initial_station: Union[str, None] = None # assigned later
        self.ideal_departure_time: Union[str, None] = None
        self.ideal_departure_time_minutes: Union[int, None] = None
        self.departure_window_minutes: Union[tuple[int, int], None] = None
        self.departure_profit: float = 0.0
        self.compulsory_stops: list[str] = []
        self.timetable_row: dict = {}

    def init_schedule(self) -> pyo.Var:
        """Initialize the schedule variable for this train."""
        return pyo.Var(range(self.schedule_length), domain=pyo.Binary, name=f"x_{self.id}")

    def get_profit(self, model: pyo.ConcreteModel, network: RailNetwork) -> float:
        """
        Calculate profit for train based on its schedule

        Arguments:
            model: Pyomo model containing the schedule variables
        Returns:
            profit (float): Profit calculated based on schedule and train characteristics
        """
        delay_penalty = self.profit / self.max_waiting_time if self.max_waiting_time > 0 else 0

        fastest_time = network.compute_fastest_travel_time(self.initial_station, self.destination_station)
        if fastest_time is None:
            return 0
        actual_time = network.compute_travel_time_in_schedule(model, self.id, self.initial_station, self.destination_station)
        delay_cost = (actual_time - fastest_time) * delay_penalty
        return self.profit - delay_cost