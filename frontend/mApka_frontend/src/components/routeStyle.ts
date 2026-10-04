// src/components/routeStyle.ts — shared mode styling for map layer and panel
export interface ModeStyle {
  color: string;
  label: string;
  icon: string;
  dashArray?: string;
}

export function modeStyle(mode: string): ModeStyle {
  switch (mode) {
    case 'WALK':
      return { color: '#94a3b8', label: 'Pieszo', icon: '🚶', dashArray: '2 10' };
    case 'BICYCLE':
      return { color: '#22c55e', label: 'Rower', icon: '🚲' };
    case 'TRAM':
      return { color: '#f97316', label: 'Tramwaj', icon: '🚋' };
    case 'BUS':
      return { color: '#3b82f6', label: 'Autobus', icon: '🚌' };
    case 'RAIL':
      return { color: '#a855f7', label: 'Kolej', icon: '🚆' };
    default:
      return { color: '#a855f7', label: 'Przejazd', icon: '🚏' };
  }
}
