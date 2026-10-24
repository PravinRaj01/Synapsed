/**
 * Print one part of the page. While the print dialog is open the body carries data-printing="<name>", and the print
 * stylesheet hides everything except the element with id "<name>-print". The mark is removed when printing ends.
 */
export function printSection(name: string): void {
  const body = document.body
  body.dataset.printing = name
  const done = () => {
    delete body.dataset.printing
    window.removeEventListener('afterprint', done)
  }
  window.addEventListener('afterprint', done)
  window.print()
}
