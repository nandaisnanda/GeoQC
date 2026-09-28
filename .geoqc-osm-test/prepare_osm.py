import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

root = Path('.geoqc-osm-test')
data = json.loads((root / 'osm-buildings.json').read_text(encoding='utf-8'))
rows = []
for element in data['elements']:
    coords = [(point['lon'], point['lat']) for point in element.get('geometry', [])]
    if len(coords) >= 4:
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        polygon = Polygon(coords)
        rows.append({'osm_id': element['id'], 'building': element.get('tags', {}).get('building'), 'geometry': polygon})

clean = gpd.GeoDataFrame(rows, crs='EPSG:4326')
messy = clean.copy()
# Defect 1: turn the first OSM footprint into a deterministic bow-tie.
minx, miny, maxx, maxy = messy.geometry.iloc[0].bounds
messy.at[0, 'geometry'] = Polygon([(minx, miny), (maxx, maxy), (minx, maxy), (maxx, miny), (minx, miny)])
# Defect 2: inject one consecutive duplicate vertex into another real footprint.
coords = list(messy.geometry.iloc[1].exterior.coords)
coords.insert(2, coords[1])
messy.at[1, 'geometry'] = Polygon(coords)

clean.to_file(root / 'osm-buildings-original.geojson', driver='GeoJSON')
messy.to_file(root / 'osm-buildings-messy.geojson', driver='GeoJSON')
print(f'features={len(messy)}')
print(f'raw_osm_invalid={int((~clean.geometry.is_valid).sum())}')
print(f'messy_invalid_shapely={int((~messy.geometry.is_valid).sum())}')
print(f'injected_osm_ids={[int(messy.osm_id.iloc[0]), int(messy.osm_id.iloc[1])]}')
