// src/App.tsx
import { useEffect, useState } from 'react';
import {
  MapContainer, TileLayer, Marker, Popup, useMap, useMapEvents,
} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import * as L from 'leaflet';
import { startIcon, metaIcon } from './map/clayIcons';
import { useAppStore } from './store/useAppStore';
import { api } from './api/client';
import { logger } from './utils/logger';
import { Map, User } from 'lucide-react';
import ProfilePage from './profile/ProfilePage';




// JAWNA ikona pinezki – żadnej magii, Vite nie może popsuć ścieżek

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
        <Marker position={[origin.lat, origin.lon]} icon={startIcon}>
          <Popup>START</Popup>
        </Marker>
      )}
      {destination && (
        <Marker position={[destination.lat, destination.lon]} icon={metaIcon}>
          <Popup>META 🏁</Popup>
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
    <div className="absolute top-4 left-4 z-[1000] w-72 bg-white p-4 rounded-lg shadow-lg flex flex-col gap-2">
      <h1 className="text-xl font-bold text-gray-800">Health Routes 🚲</h1>

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

      <p className="text-xs text-gray-600">START: {fmt(origin)}</p>
      <p className="text-xs text-gray-600">CEL: {fmt(destination)}</p>

      <UserBox />
    </div>
  );
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
      </MapContainer>
      <ControlPanel />
    </div>
  );
}

export default App;