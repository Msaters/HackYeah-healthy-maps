// src/components/RouteLayer.tsx — rysuje trasy z /api/routes (wewnątrz MapContainer)
import { useEffect, useMemo } from 'react';
import { CircleMarker, Polyline, Tooltip, useMap } from 'react-leaflet';
import * as L from 'leaflet';
import { useRouteStore } from '../store/useRouteStore';
import { decodePolyline } from '../utils/polyline';
import { modeStyle } from './routeStyle';
import type { RoutePosition } from '../api/routes';

function decodeLegs(p: RoutePosition) {
  return p.itinerary.legs.map((leg) => ({ leg, pts: decodePolyline(leg.legGeometry.points) }));
}

export default function RouteLayer() {
  const map = useMap();
  const data = useRouteStore((s) => s.data);
  const selectedIndex = useRouteStore((s) => s.selectedIndex);

  const decoded = useMemo(() => (data ? data.positions.map(decodeLegs) : []), [data]);

  // Fit the map to the selected route whenever a new response arrives
  useEffect(() => {
    if (!data || !decoded.length) return;
    const sel = decoded[Math.min(data.default_index, decoded.length - 1)] ?? decoded[0];
    const pts = sel.flatMap((x) => x.pts);
    if (pts.length < 2) return;
    const desktop = window.innerWidth >= 768;
    map.fitBounds(L.latLngBounds(pts), desktop
      ? { paddingTopLeft: [60, 60], paddingBottomRight: [440, 60], maxZoom: 16 }
      : { paddingTopLeft: [30, 150], paddingBottomRight: [30, Math.round(window.innerHeight * 0.5)], maxZoom: 16 });
  }, [data, decoded, map]);

  if (!data) return null;

  const stops = (decoded[selectedIndex] ?? []).flatMap(({ leg }, i, arr) => {
    const out: { key: string; lat: number; lon: number; name: string; line: string | null }[] = [];
    if (i > 0) {
      const prev = arr[i - 1].leg;
      const transit = leg.route?.shortName || prev.route?.shortName;
      out.push({
        key: `s${i}`, lat: leg.from.lat, lon: leg.from.lon, name: leg.from.name,
        line: transit ? `linia ${leg.route?.shortName ?? prev.route?.shortName}` : null,
      });
    }
    return out;
  });

  return (
    <>
      {/* dimmed alternatives first so the selected route is on top */}
      {decoded.map((legs, pi) =>
        pi === selectedIndex ? null : legs.map(({ pts }, li) => (
          <Polyline
            key={`alt-${pi}-${li}`}
            positions={pts}
            interactive
            pathOptions={{ color: '#cbd5e1', weight: 3, opacity: 0.25 }}
            eventHandlers={{ click: () => useRouteStore.getState().setSelectedIndex(pi) }}
          />
        )),
      )}
      {(decoded[selectedIndex] ?? []).map(({ leg, pts }, li) => {
        const st = modeStyle(leg.mode);
        return [
          <Polyline
            key={`sel-halo-${selectedIndex}-${li}`}
            positions={pts}
            interactive={false}
            pathOptions={{ color: '#ffffff', weight: st.dashArray ? 10 : 11, opacity: 0.95, lineCap: 'round', lineJoin: 'round' }}
          />,
          <Polyline
            key={`sel-${selectedIndex}-${li}`}
            positions={pts}
            interactive
            pathOptions={{ color: st.color, weight: 7, opacity: 1, dashArray: st.dashArray, lineCap: 'round', lineJoin: 'round' }}
          >
            <Tooltip sticky>{st.icon} {st.label}{leg.route?.shortName ? ` ${leg.route.shortName}` : ''} · {Math.round(leg.duration / 60)} min</Tooltip>
          </Polyline>,
        ];
      })}
      {stops.map((s) => (
        <CircleMarker
          key={s.key}
          center={[s.lat, s.lon]}
          radius={7}
          pathOptions={{ color: '#7c3aed', weight: 3, fillColor: '#ffffff', fillOpacity: 1 }}
        >
          <Tooltip direction="top">{s.name}{s.line ? ` · ${s.line}` : ''}</Tooltip>
        </CircleMarker>
      ))}
    </>
  );
}
