/** Save text as a file through the browser. A byte-order mark makes Excel read UTF-8 CSV correctly (Malay and other accents). */
export function downloadText(filename: string, text: string, mime: string): void {
  const bom = mime.startsWith('text/csv') ? '﻿' : ''
  const url = URL.createObjectURL(new Blob([bom + text], { type: `${mime};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
