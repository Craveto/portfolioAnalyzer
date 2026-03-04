import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

export default function Popover({
  open,
  anchorRef,
  onClose,
  children,
  width = 420,
  offset = 10,
  title = "",
  ariaLabel = "Popover",
  draggable = true,
  tapToMove = true,
  followPointer = true
}) {
  const popRef = useRef(null);
  const dragRef = useRef({ active: false, dx: 0, dy: 0 });
  const backdropRef = useRef({ active: false, pointerId: null });
  const [pos, setPos] = useState({ top: 0, left: 0, placement: "bottom" });
  const [manual, setManual] = useState(false);

  const preferredWidth = useMemo(() => {
    const w = Number(width);
    return Number.isFinite(w) ? w : 420;
  }, [width]);

  const compute = () => {
    const el = anchorRef?.current;
    const pop = popRef.current;
    if (!el || !pop) return;

    const r = el.getBoundingClientRect();
    const vpW = window.innerWidth || 1024;
    const vpH = window.innerHeight || 768;

    const maxW = Math.min(preferredWidth, vpW - 18);
    pop.style.maxWidth = `${maxW}px`;

    const popRect = pop.getBoundingClientRect();
    const popW = popRect.width || maxW;
    const popH = popRect.height || 260;

    const spaceBelow = vpH - r.bottom;
    const spaceAbove = r.top;
    const placeBottom = spaceBelow >= popH + offset || spaceBelow >= spaceAbove;
    const placement = placeBottom ? "bottom" : "top";

    let top = placement === "bottom" ? r.bottom + offset : r.top - popH - offset;
    let left = r.left + r.width / 2 - popW / 2;

    left = clamp(left, 9, vpW - popW - 9);
    top = clamp(top, 9, vpH - popH - 9);

    setPos({ top, left, placement });
  };

  useLayoutEffect(() => {
    if (!open) return;
    if (!manual) compute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, preferredWidth, manual]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose?.();
    };
    const onReflow = () => compute();
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onReflow);
    window.addEventListener("scroll", onReflow, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onReflow);
      window.removeEventListener("scroll", onReflow, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const pop = popRef.current;
    if (!pop || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => compute());
    ro.observe(pop);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setManual(false);
  }, [open, anchorRef]);

  useEffect(() => {
    if (!open || !draggable) return;

    const onMove = (e) => {
      if (!dragRef.current.active) return;
      const pop = popRef.current;
      if (!pop) return;

      const vpW = window.innerWidth || 1024;
      const vpH = window.innerHeight || 768;

      const rect = pop.getBoundingClientRect();
      const w = rect.width || preferredWidth;
      const h = rect.height || 260;

      const left = clamp(e.clientX - dragRef.current.dx, 9, vpW - w - 9);
      const top = clamp(e.clientY - dragRef.current.dy, 9, vpH - h - 9);
      setManual(true);
      setPos((p) => ({ ...p, left, top }));
      e.preventDefault?.();
    };

    const onUp = () => {
      dragRef.current.active = false;
    };

    window.addEventListener("pointermove", onMove, { passive: false });
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [open, draggable, preferredWidth]);

  const moveToTap = (e) => {
    if (!tapToMove) return;
    const pop = popRef.current;
    if (!pop) return;
    const vpW = window.innerWidth || 1024;
    const vpH = window.innerHeight || 768;
    const rect = pop.getBoundingClientRect();
    const w = rect.width || preferredWidth;
    const h = rect.height || 260;
    const left = clamp(e.clientX - w / 2, 9, vpW - w - 9);
    const top = clamp(e.clientY - h / 2, 9, vpH - h - 9);
    setManual(true);
    setPos((p) => ({ ...p, left, top }));
  };

  if (!open) return null;

  const node = (
    <div
      className="popoverBackdrop"
      role="presentation"
      onPointerDown={(e) => {
        // Clicking outside moves the box to the pointer and optionally lets you "drag" it by moving finger/mouse.
        if (!tapToMove) {
          onClose?.();
          return;
        }
        moveToTap(e);
        if (!followPointer) return;
        backdropRef.current.active = true;
        backdropRef.current.pointerId = e.pointerId;
        try {
          e.currentTarget.setPointerCapture?.(e.pointerId);
        } catch {
          // ignore
        }
      }}
      onPointerMove={(e) => {
        if (!followPointer) return;
        if (!backdropRef.current.active) return;
        moveToTap(e);
      }}
      onPointerUp={() => {
        backdropRef.current.active = false;
        backdropRef.current.pointerId = null;
      }}
      onPointerCancel={() => {
        backdropRef.current.active = false;
        backdropRef.current.pointerId = null;
      }}
    >
      <div
        className={`popoverCard ${pos.placement === "top" ? "top" : "bottom"}`}
        ref={popRef}
        role="dialog"
        aria-label={ariaLabel}
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
        onPointerMove={(e) => e.stopPropagation()}
        style={{ top: pos.top, left: pos.left }}
      >
        <div className="popoverHead" onPointerDown={(e) => e.stopPropagation()}>
          <div className="strong">{title}</div>
          <button className="btn ghost sm" type="button" onClick={() => onClose?.()} aria-label="Close" onPointerDown={(e) => e.stopPropagation()}>
            Close
          </button>
        </div>
        {draggable ? (
          <div
            className="popoverDrag"
            onPointerDown={(e) => {
              e.stopPropagation();
              const pop = popRef.current;
              if (!pop) return;
              const rect = pop.getBoundingClientRect();
              dragRef.current.active = true;
              dragRef.current.dx = e.clientX - rect.left;
              dragRef.current.dy = e.clientY - rect.top;
              setManual(true);
              try {
                e.currentTarget.setPointerCapture?.(e.pointerId);
              } catch {
                // ignore
              }
              e.preventDefault?.();
            }}
            role="button"
            tabIndex={0}
            aria-label="Drag popover"
            title="Drag"
          >
            <span />
            <span />
            <span />
          </div>
        ) : null}
        <div className="popoverBody" onPointerDown={(e) => e.stopPropagation()}>
          {children}
        </div>
      </div>
    </div>
  );

  // Render to body so it's not affected by transformed parents (fixes "only inside container").
  return typeof document !== "undefined" ? createPortal(node, document.body) : node;
}
