export function displayStatus(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (!normalized) return "Unknown";
  return normalized.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
