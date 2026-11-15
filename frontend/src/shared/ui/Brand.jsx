import React from "react";
export function Brand({ onClick }) {
  return (
    <a
      className="brand"
      href="#main"
      onClick={onClick}
      aria-label="Альфа-Курс — главная"
    >
      <img
        src="/brand/alfa-kurs.svg"
        width="153"
        height="30"
        alt="Альфа-Курс"
      />
    </a>
  );
}
