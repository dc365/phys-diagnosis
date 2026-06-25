MapLibre glyph PBF files for offline text labels.

Current use:
- `Noto Sans Regular/0-255.pbf` renders contour value labels such as `1002.00 hPa`.

The file was fetched from the MapLibre demo glyph service and vendored locally so
the map page can run in intranet demos without requesting online glyph resources.
If labels need Chinese text later, add the corresponding Unicode ranges for the
same font stack and keep `frontend/map.js` glyphs pointed at this directory.
