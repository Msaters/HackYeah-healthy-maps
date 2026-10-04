// src/map/clayIcons.ts
import * as L from 'leaflet';
import startIconUrl from '../assets/pictures/start.png';
import metaIconUrl from '../assets/pictures/meta.png';

export const startIcon = L.icon({
  iconUrl: startIconUrl,
  iconSize: [44, 44],
  iconAnchor: [22, 40],
  popupAnchor: [0, -36],
});

export const metaIcon = L.icon({
  iconUrl: metaIconUrl,
  iconSize: [44, 44],
  iconAnchor: [22, 40],
  popupAnchor: [0, -36],
});