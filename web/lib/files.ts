export const ACCEPT = {
  extensions: [".pdf", ".epub", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".txt", ".md"],
  maxBytes: 200 * 1024 * 1024,
};

export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ACCEPT.extensions.some((e) => name.endsWith(e)))
    return `Unsupported type. Allowed: ${ACCEPT.extensions.join(" ")}`;
  if (file.size === 0) return "File is empty";
  if (file.size > ACCEPT.maxBytes) return "File is larger than 200 MB";
  return null;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
