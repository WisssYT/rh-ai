import { useEffect, useRef } from "react";

/**
 * Hero focal point: three CV sheets in CSS 3D (no WebGL - transforms are composited and cheap).
 *
 * Motion, once, on mount (~1.3 s total, never blocks the copy/CTA beside it):
 *   1. the two back sheets fan out from behind the front sheet (transform only, staggered 90 ms)
 *   2. a marker stroke sweeps across one line of the front CV (scaleX)
 *   3. a mono margin note "p1 · s4" fades in, pointing at the highlighted line
 * Interaction: with a fine pointer, the whole stack tilts at most ±5° toward the pointer while it is
 * over the hero, eased by a requestAnimationFrame loop that stops once settled. Nothing runs when idle.
 * prefers-reduced-motion / coarse pointers: the final pose is shown statically, no tilt.
 */
export function PaperStack({ trackRef }: { trackRef: React.RefObject<HTMLElement> }) {
  const rig = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const area = trackRef.current;
    const el = rig.current;
    if (!area || !el) return;
    const fine = window.matchMedia("(pointer: fine) and (hover: hover)").matches;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!fine || reduced) return;
    // Eased toward the pointer by a rAF loop that only runs while the stack is settling
    // (no CSS transition restarted on every pointermove, no work when idle).
    let frame = 0;
    let tx = 0, ty = 0; // target, -1..1
    let cx = 0, cy = 0; // current
    const step = () => {
      cx += (tx - cx) * 0.16;
      cy += (ty - cy) * 0.16;
      el.style.transform = `rotateX(${(9 - cy * 5).toFixed(2)}deg) rotateY(${(-16 + cx * 5).toFixed(2)}deg) rotateZ(2deg)`;
      frame = Math.abs(tx - cx) + Math.abs(ty - cy) > 0.002 ? requestAnimationFrame(step) : 0;
    };
    const kick = () => {
      if (!frame) frame = requestAnimationFrame(step);
    };
    const onMove = (e: PointerEvent) => {
      const r = area.getBoundingClientRect();
      tx = Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width) * 2 - 1));
      ty = Math.max(-1, Math.min(1, ((e.clientY - r.top) / r.height) * 2 - 1));
      kick();
    };
    const onLeave = () => {
      tx = ty = 0;
      kick();
    };
    area.addEventListener("pointermove", onMove, { passive: true });
    area.addEventListener("pointerleave", onLeave);
    return () => {
      area.removeEventListener("pointermove", onMove);
      area.removeEventListener("pointerleave", onLeave);
      cancelAnimationFrame(frame);
    };
  }, [trackRef]);

  const lines = (widths: number[]) => widths.map((w, i) => <span key={i} className="ps-line" style={{ width: `${w}%` }} />);

  return (
    <div className="ps-stage" aria-hidden="true">
      <div className="ps-floor" />
      <div className="ps-rig" ref={rig}>
        <div className="ps-sheet ps-3">
          <span className="ps-head" style={{ width: "38%" }} />
          {lines([88, 72, 80, 64, 85, 58, 76, 70, 82])}
        </div>
        <div className="ps-sheet ps-2">
          <span className="ps-head" style={{ width: "44%" }} />
          {lines([82, 90, 66, 78, 54, 86, 72, 60])}
        </div>
        <div className="ps-sheet ps-1">
          <div className="ps-name">Sami Arfaoui</div>
          <div className="ps-meta">Backend developer · Tunis</div>
          <div className="ps-section">Experience</div>
          <div className="ps-text">Software Engineer, Cedar Logistics</div>
          <div className="ps-text">
            <span className="ps-mark">Built Python APIs for inventory.</span>
          </div>
          {lines([84, 70])}
          <div className="ps-section">Skills</div>
          {lines([62, 48])}
          <div className="ps-note">
            <span className="ps-leader" />
            <span className="ps-note-ref">p1 · s4</span>
            <span className="ps-note-text">evidence for “Python backend”</span>
          </div>
        </div>
      </div>
    </div>
  );
}
