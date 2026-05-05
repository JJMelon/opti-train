# Multi-Track Rail Network Format Specification (MRTS v1.0)

## Overview
The Multi-track Rail network Standard (MRTS) is a JSON-based format for representing complex rail networks with multiple tracks, multi-train capacity stations, branching junctions, and side tracks.

## Core Concepts

- **Network**: A complete rail system containing tracks, stations, and junctions
- **Station**: A location where trains can stop, with platform capacity
- **Track**: A directional rail segment connecting two points
- **Junction**: A point where tracks branch, merge, or cross
- **Platform**: A specific stopping location at a station with capacity limits
- **Side Track**: Auxiliary track for storage, maintenance, or bypass

## File Structure

### Main Network File (network.json)

```json
{
  "network": {
    "id": "string",
    "name": "string",
    "version": "1.0",
    "created": "ISO-8601 timestamp",
    "description": "string"
  },
  "metadata": {
    "crs": "EPSG:4326",  // Coordinate Reference System
    "units": "meters",
    "timezone": "string"
  },
  "stations": [...],
  "tracks": [...],
  "junctions": [...],
  "side_tracks": [...]
}
```

## Components

### 1. Stations

Represents passenger/cargo stations with multiple platforms and capacity.

```json
{
  "stations": [
    {
      "id": "STN_001",
      "name": "Central Station",
      "coordinates": {
        "lat": 44.5,
        "lon": -73.2
      },
      "type": "terminal|intermediate|junction_station",
      "max_simultaneous_trains": 4,
      "platforms": [
        {
          "id": "PF_001",
          "name": "Platform 1",
          "capacity": 1,
          "track_connections": ["TRK_001", "TRK_002"],
          "type": "passenger|freight|mixed",
          "length_meters": 300
        },
        {
          "id": "PF_002",
          "name": "Platform 2",
          "capacity": 1,
          "track_connections": ["TRK_003", "TRK_004"],
          "type": "mixed",
          "length_meters": 300
        }
      ],
      "dwell_time_seconds": 120
    }
  ]
}
```

### 2. Tracks

Represents directional rail segments between stations and junctions.

```json
{
  "tracks": [
    {
      "id": "TRK_001",
      "name": "Main Line North",
      "from_id": "STN_001",
      "to_id": "STN_002",
      "type": "main|branch|connector",
      "length_meters": 5000,
      "coordinates": [
        {"lat": 44.5, "lon": -73.2},
        {"lat": 44.6, "lon": -73.1}
      ],
      "properties": {
        "speed_limit_kmh": 100,
        "bidirectional": false,
        "num_lanes": 2
      },
      "capacity": {
        "max_trains": 2
      }
    }
  ]
}
```

### 3. Junctions

Represents points where tracks branch, merge, or cross.

```json
{
  "junctions": [
    {
      "id": "JCT_001",
      "name": "North Junction",
      "coordinates": {
        "lat": 44.55,
        "lon": -73.15
      },
      "connected_tracks": [
        {
          "track_id": "TRK_001",
          "direction": "incoming"
        },
        {
          "track_id": "TRK_002",
          "direction": "outgoing"
        },
        {
          "track_id": "TRK_003",
          "direction": "incoming"
        }
      ]
    }
  ]
}
```

### 4. Side Tracks

Represents auxiliary tracks for storage, maintenance, or bypass.

```json
{
  "side_tracks": [
    {
      "id": "SID_001",
      "name": "Storage Yard 1",
      "coordinates": {
        "start": {"lat": 44.5, "lon": -73.2},
        "end": {"lat": 44.51, "lon": -73.2}
      },
      "length_meters": 1000,
      "capacity": {
        "max_trains": 8
      },
      "connection_points": [
        {
          "connects_to": "TRK_001",
          "junction_id": "JCT_001",
          "type": "bidirectional|one_way"
        }
      ],
      "properties": {
        "parking_spots": 8
      }
    }
  ]
}
```

## Advanced Features

### Multi-Track Segments

For tracks with multiple parallel rails:

```json
{
  "tracks": [
    {
      "id": "TRK_004",
      "name": "Double-Track Main Line",
      "from_id": "STN_001",
      "to_id": "STN_003",
      "type": "main",
      "multi_track": {
        "num_tracks": 2,
        "track_designations": [
          {"lane": 1, "direction": "north", "speed_limit_kmh": 120},
          {"lane": 2, "direction": "south", "speed_limit_kmh": 120}
        ],
        "separation_meters": 2.5
      },
      "properties": {
        "speed_limit_kmh": 120,
        "bidirectional": false,
        "num_lanes": 2
      }
    }
  ]
}
```

### Station Platform Assignments

For complex multi-track platforms:

```json
{
  "platforms": [
    {
      "id": "PF_003",
      "name": "Platform 3 Multi-Track",
      "capacity": 2,
      "assigned_tracks": [
        {
          "track_id": "TRK_004",
          "lane": 1,
          "position": "north_side"
        },
        {
          "track_id": "TRK_004",
          "lane": 2,
          "position": "south_side"
        }
      ],
      "type": "mixed",
      "length_meters": 300
    }
  ]
}
```

### Train Scheduling Constraints

Optional file for capacity and scheduling:

```json
{
  "constraints": [
    {
      "track_id": "TRK_001",
      "min_headway_seconds": 300
    },
    {
      "station_id": "STN_001",
      "platform_id": "PF_001",
      "min_dwell_time_seconds": 120,
      "max_dwell_time_seconds": 600
    }
  ]
}
```

## Data Validation Rules

1. **Referential Integrity**: All `*_id` references must exist in their respective sections
2. **Coordinate Consistency**: Coordinates must be valid and within network bounds
3. **Capacity Limits**: `max_trains` must be positive integers
4. **Track Connections**: Tracks must have both `from_id` and `to_id` in the stations list
5. **Platform Connections**: Platform `track_connections` must reference existing track IDs
6. **Junction Consistency**: All connected tracks must reference the junction ID
7. **Side Track Connections**: Must connect to valid junctions or tracks

## File Organization

```
rail_network/
├── network.json              # Main network definition
├── stations.json             # Detailed station definitions
├── tracks.json               # Track definitions
├── junctions.json            # Junction definitions
├── side_tracks.json          # Side track definitions
├── constraints.json          # Scheduling constraints
└── README.md                 # Network documentation
```

## Example Use Cases

### 1. Simple Station with Double Tracks
```json
{
  "station": {
    "id": "STN_002",
    "name": "Downtown Station",
    "platforms": [
      {
        "id": "PF_A",
        "capacity": 2,
        "track_connections": ["TRK_010", "TRK_011"]
      }
    ]
  }
}
```

### 2. Junction with Split and Merge
```json
{
  "junction": {
    "id": "JCT_002",
    "type": "split",
    "connected_tracks": [
      {"track_id": "TRK_020", "direction": "incoming"},
      {"track_id": "TRK_021", "direction": "outgoing"},
      {"track_id": "TRK_022", "direction": "outgoing"}
    ]
  }
}
```

## Extensibility

Additional fields can be added to any component using a `custom_properties` object:

```json
{
  "id": "STN_001",
  "name": "Central Station",
  "custom_properties": {
    "operator": "Regional Transit Authority",
    "accessibility_rating": 5,
    "parking_spaces": 500
  }
}
```

## Versioning

- Version 1.0: Initial release with basic multi-track, junction, and side track support
- Future: Real-time train positioning, dynamic capacity, conflict resolution

---

**Last Updated**: April 2026
**Status**: Active
