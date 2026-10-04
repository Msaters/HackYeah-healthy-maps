// src/App.tsx
import { useEffect, useRef, useState } from 'react';
import {
  MapContainer, TileLayer, Marker, Popup, useMap, useMapEvents,
} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import * as L from 'leaflet';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';
import { useAppStore } from './store/useAppStore';
import { api } from './api/client';
import { logger } from './utils/logger';
import { Map, User } from 'lucide-react';
import ProfilePage from './profile/ProfilePage';
import RouteLayer from './components/RouteLayer';
import RoutePanel from './components/RoutePanel';
import { useRouteStore } from './store/useRouteStore';



// JAWNA ikona pinezki – żadnej magii, Vite nie może popsuć ścieżek
const defaultIcon = L.icon({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
  iconSize: [25, 41],    // rozmiar ikony w px
  iconAnchor: [12, 41],  // który piksel to "czubek" pinezki
  popupAnchor: [1, -34], // gdzie otwiera się dymek
  shadowSize: [41, 41],
});

// 👻 Przelicza rozmiar mapy po załadowaniu CSS (likwiduje szare pasy)
function MapRefresher() {
  const map = useMap();
  useEffect(() => {
    const t = setTimeout(() => map.invalidateSize(), 100);
    return () => clearTimeout(t);
  }, [map]);
  return null;
}


function App() {
  const view = useAppStore((s) => s.view);
  return (
    <>
      {view === 'map' ? <MapScreen /> : <ProfilePage />}
      <BottomNav />
    </>
  );
}


function BottomNav() {
  const view = useAppStore((s) => s.view);
  const setView = useAppStore((s) => s.setView);
  return (
    <nav className="fixed bottom-4 left-1/2 z-[1100] flex -translate-x-1/2 gap-1 rounded-full bg-white px-2 py-2 shadow-lg">
      <button
        onClick={() => setView('map')}
        className={`flex items-center gap-1 rounded-full px-4 py-2 text-sm font-semibold ${
          view === 'map' ? 'bg-violet-600 text-white' : 'text-gray-600 hover:bg-gray-100'
        }`}
      >
        <Map size={18} /> Mapa
      </button>
      <button
        onClick={() => setView('profile')}
        className={`flex items-center gap-1 rounded-full px-4 py-2 text-sm font-semibold ${
          view === 'profile' ? 'bg-violet-600 text-white' : 'text-gray-600 hover:bg-gray-100'
        }`}
      >
        <User size={18} /> Profil
      </button>
    </nav>
  );
}



// 🖱️ Maszyna stanów kliknięć (wymóg C)
function MapClickHandler() {
  const mapClickTarget = useAppStore((s) => s.mapClickTarget);
  const setOrigin = useAppStore((s) => s.setOrigin);
  const setDestination = useAppStore((s) => s.setDestination);
  const setMapClickTarget = useAppStore((s) => s.setMapClickTarget);

  useMapEvents({
    click(e) {
      // 🖱️ ZAWSZE logujemy kliknięcie – nawet gdy tryb nie jest uzbrojony
      logger.map(
        `🖱️ kliknięcie: lat=${e.latlng.lat.toFixed(5)}, lon=${e.latlng.lng.toFixed(5)} | tryb: ${mapClickTarget ?? 'brak'}`
      );
      if (!mapClickTarget) return;
      const point = { lat: e.latlng.lat, lon: e.latlng.lng };
      if (mapClickTarget === 'origin') setOrigin(point);
      else setDestination(point);
      setMapClickTarget(null);
    },
  });
  return null;
}

// 📍 Pinezki START / CEL – teraz z jawną ikoną
function PointsMarkers() {
  const origin = useAppStore((s) => s.origin);
  const destination = useAppStore((s) => s.destination);
  return (
    <>
      {origin && (
        <Marker position={[origin.lat, origin.lon]} icon={defaultIcon}>
          <Popup>START</Popup>
        </Marker>
      )}
      {destination && (
        <Marker position={[destination.lat, destination.lon]} icon={defaultIcon}>
          <Popup>CEL</Popup>
        </Marker>
      )}
    </>
  );
}

// 👤 Sekcja usera: logowanie demo + przywracanie stanu (kontrakt 5.1)
function UserBox() {
  const user = useAppStore((s) => s.user);
  const setUser = useAppStore((s) => s.setUser);
  const [error, setError] = useState<string | null>(null);

  // Przy ładowaniu strony próbujemy przywrócić usera: GET /me
  useEffect(() => {
    api.getMe().then(setUser).catch(() => undefined);
    // .catch "połyka" błąd – jeśli backend nie działa, po prostu pokażemy przycisk
  }, [setUser]);

  const handleLogin = async () => {
    try {
      setError(null);
      const res = await api.loginDemo();
      setUser(res.user); // 🚨 specyfikacja: token IGNORUJEMY, zapisujemy tylko usera
    } catch {
      setError('Brak połączenia z backendem. Czy serwer FastAPI działa?');
    }
  };

  if (user) {
    return (
      <div className="border-t border-gray-200 pt-2 text-xs text-gray-700">
        👤 {user.name} ({user.email})<br />
        🎯 Cel: <b>{user.goal.target_steps}</b> kroków /{' '}
        <b>{user.goal.target_calories}</b> kcal
      </div>
    );
  }

  return (
    <div className="border-t border-gray-200 pt-2">
      <button
        onClick={handleLogin}
        className="w-full rounded-md bg-gray-800 px-3 py-2 text-sm font-semibold text-white hover:bg-gray-700"
      >
        Zaloguj jako demo
      </button>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

// 🎛️ Panel sterowania
function ControlPanel() {
  const mapClickTarget = useAppStore((s) => s.mapClickTarget);
  const setMapClickTarget = useAppStore((s) => s.setMapClickTarget);
  const origin = useAppStore((s) => s.origin);
  const destination = useAppStore((s) => s.destination);

  const fmt = (p: { lat: number; lon: number } | null) =>
    p ? `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}` : '—';

  return (
    <div className="absolute top-2 left-2 z-[1000] w-[min(18rem,calc(100vw-1rem))] bg-white p-3 md:top-4 md:left-4 md:p-4 rounded-lg shadow-lg flex flex-col gap-2">
      <h1 className="hidden text-xl font-bold text-gray-800 md:block">Health Routes 🚲</h1>

      <button
        onClick={() => setMapClickTarget(mapClickTarget === 'origin' ? null : 'origin')}
        className={`rounded-md px-3 py-2 text-sm font-semibold transition-colors ${
          mapClickTarget === 'origin'
            ? 'bg-blue-600 text-white'
            : 'bg-blue-100 text-blue-800 hover:bg-blue-200'
        }`}
      >
        {mapClickTarget === 'origin' ? 'Teraz kliknij w mapę…' : 'Kliknij mapę, aby ustawić START'}
      </button>

      <button
        onClick={() => setMapClickTarget(mapClickTarget === 'destination' ? null : 'destination')}
        className={`rounded-md px-3 py-2 text-sm font-semibold transition-colors ${
          mapClickTarget === 'destination'
            ? 'bg-green-600 text-white'
            : 'bg-green-100 text-green-800 hover:bg-green-200'
        }`}
      >
        {mapClickTarget === 'destination' ? 'Teraz kliknij w mapę…' : 'Kliknij mapę, aby ustawić CEL'}
      </button>

      <p className="hidden text-xs text-gray-600 md:block">START: {fmt(origin)}</p>
      <p className="hidden text-xs text-gray-600 md:block">CEL: {fmt(destination)}</p>

      <UserBox />
    </div>
  );
}


// 🧭 Auto-plan: gdy START i CEL są ustawione (zależność tylko od współrzędnych); zmiana punktu czyści trasy.
// Po powrocie z Profilu (te same punkty) nie planujemy od nowa.
let lastPlannedKey: string | null = null;

function AutoPlanner() {
  const origin = useAppStore((s) => s.origin);
  const destination = useAppStore((s) => s.destination);
  const deadline = useRouteStore((s) => s.deadline);
  const hasBike = useRouteStore((s) => s.hasBike);
  const simulateSmog = useRouteStore((s) => s.simulateSmog);
  const oLat = origin?.lat, oLon = origin?.lon, dLat = destination?.lat, dLon = destination?.lon;

  useEffect(() => {
    if (oLat === undefined || oLon === undefined || dLat === undefined || dLon === undefined) {
      lastPlannedKey = null;
      useRouteStore.getState().clear();
      return;
    }
    const key = `${oLat},${oLon}>${dLat},${dLon}`;
    if (key === lastPlannedKey) return;
    lastPlannedKey = key;
    const { plan, clear } = useRouteStore.getState();
    clear();
    void plan({ lat: oLat, lon: oLon }, { lat: dLat, lon: dLon }, useAppStore.getState().user);
  }, [oLat, oLon, dLat, dLon]);

  // Re-plan (debounced) when deadline / bike / smog change; skipped on mount
  const prev = useRef(`${deadline}|${hasBike}|${simulateSmog}`);
  useEffect(() => {
    const cur = `${deadline}|${hasBike}|${simulateSmog}`;
    if (cur === prev.current) return;
    prev.current = cur;
    if (oLat === undefined || oLon === undefined || dLat === undefined || dLon === undefined) return;
    const t = setTimeout(() => {
      void useRouteStore.getState().plan(
        { lat: oLat, lon: oLon }, { lat: dLat, lon: dLon }, useAppStore.getState().user,
      );
    }, 300);
    return () => clearTimeout(t);
  }, [deadline, hasBike, simulateSmog, oLat, oLon, dLat, dLon]);
  return null;
}

function MapScreen() {
  return (
    <div className="h-[100dvh] w-full relative">
      <MapContainer
        center={[50.0614, 19.9366]}
        zoom={16}
        maxZoom={18}            // 🛑 twardy limit przybliżenia dla użytkownika
        className="h-full w-full z-0"
      >
        {/* Warstwa 1: ciemne tło (Esri Dark Gray) */}
        <TileLayer
          attribution='Tiles &copy; Esri &mdash; Esri and the GIS user community'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
          maxNativeZoom={16}    // 📦 "serwer ma dane tylko do 16…"
          maxZoom={18}   
        
        />
        {/* Warstwa 2: etykiety miast i ulic (rysowana NA tle) */}
        <TileLayer
          attribution='Tiles &copy; Esri &mdash; Esri and the GIS user community'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
          maxNativeZoom={16}
          maxZoom={18}
        />

        <MapRefresher />
        <MapClickHandler />
        <PointsMarkers />
        <RouteLayer />
      </MapContainer>
      <AutoPlanner />
      <ControlPanel />
      <RoutePanel />
    </div>
  );
}

export default App;