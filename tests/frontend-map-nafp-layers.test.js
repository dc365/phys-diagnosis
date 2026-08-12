const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('frontend/map.html', 'utf8');
const mapJs = fs.readFileSync('frontend/map.js', 'utf8');

test('map page exposes a layer data source switcher defaulting to NAFP raw grids', () => {
  assert.match(html, /id="layerSourceSelect"/);
  assert.match(html, /value="nafp" selected/);
  assert.match(html, />NAFP 原始格点</);
  assert.match(html, />诊断产品</);
});

test('map layer loading can use NAFP grid, metadata and contour endpoints', () => {
  assert.match(mapJs, /function selectedLayerSource\(\)/);
  assert.match(mapJs, /function shouldUseNafpLayerSource\(\)/);
  assert.match(mapJs, /async function loadNafpLayerData\(layer, fh\)/);
  assert.match(mapJs, /buildNafpLayerMetadataUrl\(layer, selectedPointDataCode\(\), selectedPointRunTime\(\), fh, Date\.now\(\)\)/);
  assert.match(mapJs, /buildNafpLayerGridUrl\(layer, selectedPointDataCode\(\), selectedPointRunTime\(\), fh, Date\.now\(\)\)/);
  assert.match(mapJs, /buildNafpLayerContourUrl\(layer, selectedPointDataCode\(\), selectedPointRunTime\(\), fh, Date\.now\(\)\)/);
});

test('map cancels stale NAFP layer requests before starting a new layer load', () => {
  assert.match(mapJs, /nafpLayerAbortController/);
  assert.match(mapJs, /state\.nafpLayerAbortController\?\.abort\(\)/);
  assert.match(mapJs, /new AbortController\(\)/);
  assert.match(mapJs, /\{\s*signal:\s*controller\.signal\s*\}/);
});

test('map loads NAFP metadata, grid and contours concurrently behind one backend singleflight', () => {
  assert.match(mapJs, /const \[md, grid\] = await Promise\.all\(\[/);
  assert.match(mapJs, /loadContours\(\{ signal: controller\.signal \}\)/);
});

test('map layer loading uses sounding analysis grids when category is observed', () => {
  assert.match(mapJs, /async function loadSoundingLayerData\(layer\)/);
  assert.match(mapJs, /if \(selectedDataCategory\(\) === 'sounding'\) \{[\s\S]*?await loadSoundingLayerData\(layer, options\);\s*return;\s*\}/);
  assert.match(mapJs, /buildSoundingLayerMetadataUrl\(layer, selectedSoundingCsvPath\(\), 500, Date\.now\(\)\)/);
  assert.match(mapJs, /buildSoundingLayerGridUrl\(layer, selectedSoundingCsvPath\(\), 500, Date\.now\(\)\)/);
  assert.match(mapJs, /buildSoundingLayerContourUrl\(layer, selectedSoundingCsvPath\(\), 500, Date\.now\(\)\)/);
});
