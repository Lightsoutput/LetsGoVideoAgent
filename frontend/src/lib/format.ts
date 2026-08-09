export function formatTimestamp(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return [hours, minutes, seconds].map((value) => `${value}`.padStart(2, "0")).join(":");
  }
  return [minutes, seconds].map((value) => `${value}`.padStart(2, "0")).join(":");
}

export function formatDuration(milliseconds: number | null): string {
  return milliseconds === null ? "--:--" : formatTimestamp(milliseconds);
}

export function formatCost(cost: string): string {
  const value = Number(cost);
  if (!Number.isFinite(value) || value === 0) return "$0.0000";
  return `$${value.toFixed(4)}`;
}

export function formatCny(cost: string | number): string {
  const value = Number(cost);
  if (!Number.isFinite(value) || value === 0) return "¥0.000000";
  return `¥${value.toFixed(value < 0.01 ? 6 : 4)}`;
}
