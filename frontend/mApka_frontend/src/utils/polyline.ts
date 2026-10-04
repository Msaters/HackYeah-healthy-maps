// src/utils/polyline.ts
// Google encoded polyline decoder (precision 5) -> [lat, lon][]
export function decodePolyline(encoded: string): [number, number][] {
  const out: [number, number][] = [];
  let index = 0;
  let lat = 0;
  let lon = 0;

  const readValue = (): number => {
    let result = 0;
    let shift = 0;
    let byte: number;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20 && index < encoded.length);
    return result & 1 ? ~(result >> 1) : result >> 1;
  };

  while (index < encoded.length) {
    lat += readValue();
    if (index >= encoded.length) break;
    lon += readValue();
    out.push([lat / 1e5, lon / 1e5]);
  }
  return out;
}
