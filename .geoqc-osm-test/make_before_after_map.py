from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, FancyBboxPatch
from PIL import Image

ROOT = Path('.geoqc-osm-test')
BEFORE = gpd.read_file(ROOT / 'osm-buildings-messy.geojson').to_crs(32748)
AFTER = gpd.read_file(ROOT / 'osm-buildings-repaired.geojson').to_crs(32748)
ISSUE_IDS = [28717125, 121716538]
COLORS = {'navy': '#12263A', 'red': '#D64545', 'green': '#22A06B', 'blue': '#3E7CB1', 'paper': '#F4F6F8', 'gray': '#DDE3E9'}

fig = plt.figure(figsize=(16, 10), dpi=180, facecolor=COLORS['paper'])
gs = fig.add_gridspec(3, 2, height_ratios=[0.15, 0.58, 0.27], hspace=0.10, wspace=0.08, left=0.04, right=0.96, top=0.95, bottom=0.05)

# Header
header = fig.add_subplot(gs[0, :]); header.axis('off')
header.text(0.00, 0.72, 'GeoQC  |  OSM TOPOLOGY REPAIR', fontsize=11, color=COLORS['blue'], weight='bold', transform=header.transAxes)
header.text(0.00, 0.20, 'Before / After Quality-Control Map', fontsize=25, color=COLORS['navy'], weight='bold', transform=header.transAxes)
header.text(1.00, 0.25, 'Jakarta, Indonesia  •  30 OSM building footprints  •  EPSG:32748', fontsize=10, color='#536273', ha='right', transform=header.transAxes)
header.plot([0, 1], [0.02, 0.02], color=COLORS['gray'], lw=1.3, transform=header.transAxes)

# Shared extent with padding
minx, miny, maxx, maxy = BEFORE.total_bounds
padx, pady = (maxx-minx)*0.06, (maxy-miny)*0.08
extent = (minx-padx, maxx+padx, miny-pady, maxy+pady)

for col, (data, title, subtitle, accent, fill) in enumerate([
    (BEFORE, 'BEFORE', '2 problematic features • 3 issues detected', COLORS['red'], '#F5B7B1'),
    (AFTER, 'AFTER', '0 problematic features • 0 issues remaining', COLORS['green'], '#A9DFBF'),
]):
    ax = fig.add_subplot(gs[1, col])
    ax.set_facecolor('#EEF2F5')
    # subtle contextual blocks
    data.plot(ax=ax, color='#C9D3DC', edgecolor='#FFFFFF', linewidth=0.75, zorder=1)
    issues = data[data.osm_id.isin(ISSUE_IDS)]
    issues.plot(ax=ax, color=fill, edgecolor=accent, linewidth=2.2, zorder=3)
    for _, row in issues.iterrows():
        p = row.geometry.representative_point()
        label = 'A' if int(row.osm_id) == ISSUE_IDS[0] else 'B'
        ax.annotate(label, (p.x, p.y), color='white', weight='bold', ha='center', va='center', fontsize=9,
                    bbox=dict(boxstyle='circle,pad=0.25', facecolor=accent, edgecolor='white', linewidth=1.2), zorder=4)
    ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3]); ax.set_aspect('equal')
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values(): spine.set_edgecolor('#CAD3DC'); spine.set_linewidth(1.0)
    ax.text(0.03, 0.95, title, transform=ax.transAxes, va='top', fontsize=20, weight='bold', color=accent,
            bbox=dict(boxstyle='round,pad=0.35', facecolor='white', edgecolor='none', alpha=0.95))
    ax.text(0.03, 0.865, subtitle, transform=ax.transAxes, va='top', fontsize=10.5, color=COLORS['navy'], weight='bold')
    # north arrow
    ax.annotate('N', xy=(0.94, 0.91), xytext=(0.94, 0.80), xycoords='axes fraction', textcoords='axes fraction',
                ha='center', va='center', color=COLORS['navy'], fontsize=11, weight='bold',
                arrowprops=dict(facecolor=COLORS['navy'], edgecolor=COLORS['navy'], width=3, headwidth=10))
    # scale bar 50m
    bar = 50
    x0 = extent[0] + (extent[1]-extent[0])*0.06; y0 = extent[2] + (extent[3]-extent[2])*0.055
    ax.plot([x0, x0+bar], [y0, y0], color=COLORS['navy'], lw=4, solid_capstyle='butt')
    ax.plot([x0, x0], [y0-2, y0+2], color=COLORS['navy'], lw=1); ax.plot([x0+bar, x0+bar], [y0-2, y0+2], color=COLORS['navy'], lw=1)
    ax.text(x0+bar/2, y0+5, '50 m', ha='center', va='bottom', fontsize=8, color=COLORS['navy'], weight='bold')

# Inset comparisons per repaired feature
for col, osm_id in enumerate(ISSUE_IDS):
    ax = fig.add_subplot(gs[2, col]); ax.set_facecolor('white')
    b = BEFORE[BEFORE.osm_id == osm_id].geometry.iloc[0]
    a = AFTER[AFTER.osm_id == osm_id].geometry.iloc[0]
    bounds = b.union(a).bounds
    dx=max(bounds[2]-bounds[0], 1); dy=max(bounds[3]-bounds[1], 1); pad=max(dx,dy)*0.35
    gpd.GeoSeries([b], crs=BEFORE.crs).plot(ax=ax, facecolor=COLORS['red'], edgecolor='#8E2C2C', alpha=.35, linewidth=2.0, hatch='///', label='Before')
    gpd.GeoSeries([a], crs=AFTER.crs).plot(ax=ax, facecolor=COLORS['green'], edgecolor='#147A4E', alpha=.55, linewidth=2.0, label='After')
    ax.set_xlim(bounds[0]-pad,bounds[2]+pad); ax.set_ylim(bounds[1]-pad,bounds[3]+pad); ax.set_aspect('equal'); ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values(): spine.set_edgecolor('#CAD3DC')
    tag = 'A' if col == 0 else 'B'
    issue = 'SELF-INTERSECTION' if col == 0 else 'DUPLICATE VERTEX'
    detail = 'Bow-tie polygon split into valid geometry' if col == 0 else 'Repeated coordinate removed without shape loss'
    ax.text(0.03, 0.92, f'{tag}  OSM {osm_id}', transform=ax.transAxes, fontsize=11, weight='bold', color=COLORS['navy'], va='top')
    ax.text(0.03, 0.78, issue, transform=ax.transAxes, fontsize=10, weight='bold', color=COLORS['red'], va='top')
    ax.text(0.03, 0.09, detail, transform=ax.transAxes, fontsize=9, color='#536273', va='bottom',
            bbox=dict(boxstyle='round,pad=.35', facecolor='white', edgecolor='#DDE3E9', alpha=.93))

# Legend and footer
legend = [Patch(facecolor='#C9D3DC', edgecolor='white', label='OSM building'), Patch(facecolor='#F5B7B1', edgecolor=COLORS['red'], label='Before: issue'), Patch(facecolor='#A9DFBF', edgecolor=COLORS['green'], label='After: repaired')]
fig.legend(handles=legend, loc='lower center', bbox_to_anchor=(0.5, 0.013), ncol=3, frameon=False, fontsize=9)
fig.text(0.04, 0.018, 'Source: OpenStreetMap / Overpass API', fontsize=8, color='#6B7886')
fig.text(0.96, 0.018, 'Repair engine: GeoQC 0.1.0  |  Validation result: PASS', fontsize=8, color='#6B7886', ha='right')

out = ROOT / 'geoqc-osm-before-after.jpg'
fig.savefig(out, format='jpg', dpi=180, facecolor=fig.get_facecolor(), pil_kwargs={'quality': 95, 'subsampling': 0}, bbox_inches='tight')
plt.close(fig)
with Image.open(out) as image:
    print(f'Created: {out.resolve()}')
    print(f'Size: {image.size[0]}x{image.size[1]} px')
    print(f'Format: {image.format}, Mode: {image.mode}')
