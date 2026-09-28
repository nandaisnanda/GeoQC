import json
from pathlib import Path

import geopandas as gpd
import geoqc
import shapely
from geoqc import repair_geometry, validate_geometry

root = Path('.geoqc-osm-test')
gdf = gpd.read_file(root / 'osm-buildings-messy.geojson')
initial = [validate_geometry(geom) for geom in gdf.geometry]
initial_issues = [
    {'row': i, 'osm_id': int(gdf.osm_id.iloc[i]), 'issues': [issue.issue_type.value for issue in result.issues]}
    for i, result in enumerate(initial) if not result.is_valid
]
repairs = [repair_geometry(geom) for geom in gdf.geometry]
repaired_geometries = [shapely.from_wkt(result.after_wkt) for result in repairs]
fixed = gdf.copy()
fixed.geometry = repaired_geometries
fixed.to_file(root / 'osm-buildings-repaired.geojson', driver='GeoJSON')
final = [validate_geometry(geom) for geom in fixed.geometry]
summary = {
    'geoqc_version': geoqc.__version__,
    'geoqc_loaded_from': str(Path(geoqc.__file__).resolve()),
    'feature_count': len(gdf),
    'initial_invalid_features': sum(not result.is_valid for result in initial),
    'initial_issue_count': sum(len(result.issues) for result in initial),
    'initial_issues': initial_issues,
    'repair_status_counts': {
        status: sum(result.status.value == status for result in repairs)
        for status in ('repaired', 'unchanged', 'failed')
    },
    'repair_action_counts': {
        issue: sum(action.issue_type.value == issue for result in repairs for action in result.actions)
        for issue in sorted({action.issue_type.value for result in repairs for action in result.actions})
    },
    'post_repair_invalid_features': sum(not result.is_valid for result in final),
    'post_repair_issue_count': sum(len(result.issues) for result in final),
    'all_output_geometries_shapely_valid': all(geom.is_valid for geom in fixed.geometry),
}
(root / 'result.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
assert '.geoqc-pypi-test' in summary['geoqc_loaded_from']
assert summary['initial_invalid_features'] >= 2
assert summary['repair_status_counts']['repaired'] >= 2
assert summary['post_repair_invalid_features'] == 0
assert summary['all_output_geometries_shapely_valid']
print('SMOKE TEST: PASS')
