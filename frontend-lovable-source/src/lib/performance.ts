const PREFIX = "spareno:";

export function performanceMark(name: string) {
  if (typeof performance === "undefined" || typeof performance.mark !== "function") return;
  performance.mark(`${PREFIX}${name}`);
}

export function performanceMeasure(name: string, start: string, end?: string) {
  if (typeof performance === "undefined" || typeof performance.measure !== "function") return;
  const measureName = `${PREFIX}${name}`;
  const startName = `${PREFIX}${start}`;
  const endName = end ? `${PREFIX}${end}` : undefined;
  try {
    performance.measure(measureName, startName, endName);
  } catch {
    // Marks are diagnostic only and must never affect startup correctness.
  }
}

