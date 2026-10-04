// Run: node --experimental-strip-types src/utils/polyline.test.mjs (Node 22)
import assert from 'node:assert/strict';
import { decodePolyline } from './polyline.ts';

const near = (a, b) => {
  assert.equal(a.length, b.length);
  a.forEach((p, i) => p.forEach((v, j) => assert.ok(Math.abs(v - b[i][j]) < 1e-5, `${v} vs ${b[i][j]}`)));
};

near(decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@'), [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]);
assert.deepEqual(decodePolyline(''), []);

// live fragment (Krakow, from /api/routes)
const live = decodePolyline('isrpHephyBCPIpAAN?FAP?F?BB@N@AXAx@D@@??H@??DCjA@?');
assert.ok(live.length > 5);
for (const [lat, lon] of live) {
  assert.ok(lat > 50.0 && lat < 50.1, `lat ${lat}`);
  assert.ok(lon > 19.9 && lon < 20.1, `lon ${lon}`);
}
console.log('polyline tests OK', live.length, 'points');
