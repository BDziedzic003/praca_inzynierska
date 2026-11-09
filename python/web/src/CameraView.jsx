// Podgląd strumienia MJPEG z serwera, obrócony zgodnie z montażem kamery.
import { useEffect, useRef, useState } from 'react';
import { CAMERA_ROTATION_DEG } from './protocol';

export function CameraView({ token }) {
  const [key, setKey] = useState(0);
  const [ok, setOk] = useState(false);
  const img = useRef(null);

  // Wykrycie pierwszej klatki (zdarzenie load dla MJPEG nie zawsze występuje)
  useEffect(() => {
    setOk(false);
    const t = setInterval(() => {
      if (img.current?.naturalWidth > 0) {
        setOk(true);
        clearInterval(t);
      }
    }, 300);
    return () => clearInterval(t);
  }, [key]);

  // Ponowne połączenie po błędzie strumienia
  const onError = () => {
    setOk(false);
    setTimeout(() => setKey((k) => k + 1), 2000);
  };

  const quarter = Math.abs(CAMERA_ROTATION_DEG) % 180 === 90;
  return (
    <div className={`camera ${quarter ? 'portrait' : ''}`}>
      <img
        key={key}
        ref={img}
        src={`/stream?token=${encodeURIComponent(token)}&t=${key}`}
        alt="Obraz z kamery robota"
        style={{ transform: `translate(-50%, -50%) rotate(${CAMERA_ROTATION_DEG}deg)` }}
        onError={onError}
      />
      {!ok && <div className="camera-overlay">Łączenie z kamerą…</div>}
    </div>
  );
}
