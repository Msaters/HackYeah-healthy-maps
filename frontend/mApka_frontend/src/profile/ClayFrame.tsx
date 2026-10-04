// src/profile/ClayFrame.tsx
import type { ReactNode } from 'react';
import clayFrame from '../assets/pictures/Ramka.png';
import clayTexture from '../assets/pictures/tekstura-gliny.png';

const FRAME_WIDTH = 56;   // grubość ramki NA EKRANIE (px)
const FRAME_SLICE = 160;  // wstęga w źródłowym PNG (px)
const OVERLAY = 0.55;     // mgiełka czytelności: 0 = surowa glina, 1 = jasny beż

interface Props {
  children: ReactNode;
  className?: string;
}

export default function ClayFrame({ children, className = '' }: Props) {
  return (
    <div
      className={className}
      style={{
        backgroundColor: '#f5f1e8',
        backgroundImage: `linear-gradient(rgba(245,241,232,${OVERLAY}), rgba(245,241,232,${OVERLAY})), url(${clayTexture})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundClip: 'padding-box', // tło NIE wyłazi poza ramkę
        border: `${FRAME_WIDTH}px solid transparent`,
        borderImageSource: `url(${clayFrame})`,
        borderImageSlice: `${FRAME_SLICE} fill`,
        borderImageRepeat: 'stretch',
      }}
    >
      {children}
    </div>
  );
}