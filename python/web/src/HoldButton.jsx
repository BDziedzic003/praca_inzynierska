// Przycisk działający podczas przytrzymania (mysz lub dotyk); kilka przycisków może być wciśniętych jednocześnie.
import { useRef, useState } from 'react';

export function HoldButton({ label, onPress, onRelease, className = '', title }) {
  const [down, setDown] = useState(false);
  const isDown = useRef(false);

  const start = (e) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    if (isDown.current) return;
    isDown.current = true;
    setDown(true);
    onPress();
  };
  const end = () => {
    if (!isDown.current) return;
    isDown.current = false;
    setDown(false);
    onRelease();
  };

  return (
    <button
      type="button"
      title={title}
      className={`hold ${className} ${down ? 'down' : ''}`}
      onPointerDown={start}
      onPointerUp={end}
      onPointerCancel={end}
      onLostPointerCapture={end}
      onContextMenu={(e) => e.preventDefault()}
    >
      {label}
    </button>
  );
}
