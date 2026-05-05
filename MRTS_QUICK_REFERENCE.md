# MRTS Quick Reference Guide

## Component Anatomy

### Station
```json
{
  "id": "STN_XXX",              // Unique identifier
  "name": "Station Name",
  "coordinates": {
    "lat": 44.4758,             // WGS84
    "lon": -73.2125
  },
  "type": "terminal|intermediate|junction_station",
  "capacity": 4,  // Total capacity
  "dwell_time_seconds": 120      // Default stop duration
}
```

### Track
```json
{
  "id": "TRK_XXX",
  "name": "Track Name",
  "from_id": "STN_001",          // Source station
  "to_id": "STN_002",            // Destination station
  "type": "main|branch|connector",
  "length_meters": 5000,
  "coordinates": [               // Path waypoints
    {"lat": 44.5, "lon": -73.2},
    {"lat": 44.6, "lon": -73.1}
  ],
  "properties": {
    "speed_limit_kmh": 100,
    "bidirectional": true|false, // Can run both directions
    "num_lanes": 1               // Number of parallel lanes
  },
  "capacity": {
    "max_trains": 2              // Simultaneous trains
  }
}
```

### Junction
```json
{
  "id": "JCT_XXX",
  "name": "Junction Name",
  "coordinates": {"lat": 44.5, "lon": -73.15},
  "connected_tracks": [
    {"track_id": "TRK_001", "direction": "incoming"},
    {"track_id": "TRK_002", "direction": "outgoing"}
  ]
}
```

### Side Track
```json
{
  "id": "SID_XXX",
  "name": "Side Track Name",
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
      "connects_to": "TRK_001",   // Track or junction ID
      "junction_id": "JCT_001",   // Optional
      "type": "bidirectional|one_way"
    }
  ],
  "properties": {
    "parking_spots": 8
  }
}
    "parking_spots": 8
  }
}
```

## ID Naming Pattern

| Component | Pattern | Example |
|-----------|---------|---------|
| Station | STN_IDENTIFIER | STN_CENTRAL, STN_NORTH |
| Track | TRK_IDENTIFIER | TRK_MAIN_N, TRK_EXPRESS |
| Junction | JCT_IDENTIFIER | JCT_SPLIT_1, JCT_MERGE |
| Platform | PF_IDENTIFIER | PF_001, PF_A |
| Side Track | SID_IDENTIFIER | SID_STORAGE_1, SID_MAINT |

## Track Types

| Type | Purpose | Speed | Typical Use |
|------|---------|-------|------------|
| main | Primary route | High | Main line service |
| side_track | Secondary/auxiliary track | Medium | Branch, storage, maintenance |

## Junction Types

Junctions connect tracks without type specification.

## Side Track Information

Side tracks are specialized tracks for storage, maintenance, bypass, or emergency use.

## Common Patterns

### Double-Track Main Line
```json
{
  "tracks": [
    {
      "id": "TRK_NORTH_1",
      "from_id": "STN_A",
      "to_id": "STN_B",
      "properties": {"num_lanes": 2, "bidirectional": false}
    }
  ]
}
```

### Branching Junction
```json
{
  "junctions": [
    {
      "id": "JCT_SPLIT",
      "type": "split",
      "connected_tracks": [
        {"track_id": "TRK_MAIN", "direction": "incoming"},
        {"track_id": "TRK_BRANCH_1", "direction": "outgoing"},
        {"track_id": "TRK_BRANCH_2", "direction": "outgoing"}
      ]
    }
  ]
}
```

### Multi-Platform Terminal
```json
{
  "stations": [
    {
      "id": "STN_TERMINAL",
      "max_simultaneous_trains": 6,
      "platforms": [
        {"id": "PF_A", "capacity": 2, "track_connections": ["TRK_1", "TRK_2"]},
        {"id": "PF_B", "capacity": 2, "track_connections": ["TRK_3", "TRK_4"]},
        {"id": "PF_C", "capacity": 2, "track_connections": ["TRK_5", "TRK_6"]}
      ]
    }
  ]
}
```

## Validation Checklist

- [ ] All IDs follow naming pattern
- [ ] Station coordinates are WGS84
- [ ] All track from_id/to_id reference valid stations
- [ ] All platform track_connections reference valid tracks
- [ ] All junction connected_tracks reference valid tracks
- [ ] All side track connection_points reference valid entities
- [ ] Platform capacity ≤ max_simultaneous_trains
- [ ] Coordinates form valid paths
- [ ] No missing required fields
- [ ] Numeric values are within valid ranges

## Python Quick Usage

```python
from mrts_utils import RailNetwork, analyze_network

# Load
network = RailNetwork.from_file('network.json')

# Validate
is_valid, errors = network.validate()

# Analyze
analysis = analyze_network(network)

# Query
path = network.get_path('STN_001', 'STN_005')
capacity = network.get_platform_capacity('STN_001')
track_info = network.get_track_info('TRK_001')

# Connected tracks at station
connected = network.get_connected_tracks('STN_001')

# Save
network.save('modified_network.json')
```

## Common Queries

### Get all tracks from a station
```python
network.get_connected_tracks('STN_001')
```

### Find path between stations
```python
network.get_path('STN_START', 'STN_END')
```

### Get station platform info
```python
network.get_platform_capacity('STN_001')
```

### Check track details
```python
network.get_track_info('TRK_001')
```

### Validate entire network
```python
is_valid, errors = network.validate()
```

## Constraints Format

```json
{
  "constraints": [
    {
      "track_id": "TRK_001",
      "min_headway_seconds": 300,      // Min time between trains
      "max_trains_per_hour": 12        // Capacity limit
    },
    {
      "station_id": "STN_001",
      "platform_id": "PF_001",
      "min_dwell_time_seconds": 120,   // Min stop time
      "max_dwell_time_seconds": 600    // Max stop time
    },
    {
      "junction_id": "JCT_001",
      "min_switching_interval_seconds": 30 // Min time between switches
    }
  ]
}
```

## Speed Reference (km/h)

| Type | Typical Speed |
|------|---------------|
| Local/Commuter | 60-90 |
| Regional | 100-140 |
| Express | 150-200 |
| High-speed | 200-320 |
| Freight | 80-120 |
| Shunting/Yard | 20-40 |

## Gauge Reference (mm)

| Gauge Type | Standard Size |
|------------|---------------|
| Standard | 1435 |
| Broad | 1600-1676 |
| Narrow | 600-1000 |

## File Size Estimates

| Network Size | Stations | Tracks | File Size |
|-------------|----------|--------|-----------|
| Small | 10-20 | 20-40 | 50-100 KB |
| Medium | 50-100 | 100-200 | 200-500 KB |
| Large | 200-500 | 500-1000 | 1-2 MB |
| Very Large | 1000+ | 2000+ | 5+ MB |

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| Invalid station reference | Track references missing station | Add station to stations array |
| Platform capacity mismatch | Platform capacity < max_simultaneous | Reduce max or add platforms |
| Circular path | Some junctions form loops | Check for unintended loops |
| Missing IDs | References to non-existent entities | Verify all references exist |

---

For detailed documentation, see `MRTS_README.md` and `RAIL_FORMAT_SPEC.md`
