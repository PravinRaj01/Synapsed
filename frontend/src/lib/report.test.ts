import { describe, expect, it, vi } from 'vitest'
import { downloadText } from './download'
import { buildHeatmap, cellStrength, csvCell, fileSlug, NO_SEGMENT, reportCsv, reportMarkdown, shortSegment, sortThemes } from './report'
import type { ThemeRow } from './vault'

const theme = (patch: Partial<ThemeRow> = {}): ThemeRow => ({
  id: 't1', label: 'Report exports time out', description: 'Large reports fail.', color: '#ec4899', frequency: 7, business_impact: 100, sentiment: 'negative',
  sentiment_counts: { positive: 0, neutral: 0, negative: 7 }, sentiment_net: -1, average_severity: 3.6, kinds: { pain_point: 6, feature_request: 1 }, sources: 5,
  segments: [{ segment_id: 's1', name: 'Enterprise', tier: 'enterprise', insights: 4 }, { segment_id: 's2', name: 'Free', tier: 'free', insights: 3 }],
  use_cases: [{ use_case: 'Monthly reporting', insights: 4 }], ...patch,
})
const a = theme()
const b = theme({ id: 't2', label: 'Bank matching', business_impact: 93, frequency: 7, average_severity: 4.2, segments: [{ segment_id: 's1', name: 'Enterprise', tier: 'enterprise', insights: 2 }, { segment_id: null, name: 'No segment', tier: null, insights: 5 }] })
const c = theme({ id: 't3', label: 'Approvals', business_impact: 60, frequency: 9, average_severity: 2, segments: [{ segment_id: 's2', name: 'Free', tier: 'free', insights: 9 }] })

describe('sortThemes', () => {
  it('orders by the chosen measure, highest first, without changing the input', () => {
    const input = [a, b, c]
    expect(sortThemes(input, 'impact').map((t) => t.label)).toEqual(['Report exports time out', 'Bank matching', 'Approvals'])
    expect(sortThemes(input, 'mentions').map((t) => t.label)).toEqual(['Approvals', 'Report exports time out', 'Bank matching']) // ties by impact
    expect(sortThemes(input, 'severity').map((t) => t.label)).toEqual(['Bank matching', 'Report exports time out', 'Approvals'])
    expect(input.map((t) => t.label)).toEqual(['Report exports time out', 'Bank matching', 'Approvals'])
  })
  it('treats a missing severity as lowest and breaks full ties by name', () => {
    const none = theme({ id: 'n', label: 'Alpha', average_severity: null, business_impact: 50, frequency: 1 })
    const twin = theme({ id: 'n2', label: 'Beta', average_severity: null, business_impact: 50, frequency: 1 })
    expect(sortThemes([twin, a, none], 'severity').map((t) => t.label)).toEqual(['Report exports time out', 'Alpha', 'Beta'])
  })
})

describe('buildHeatmap', () => {
  const h = buildHeatmap([a, b, c])
  it('has a column per segment, busiest first and "No segment" last', () => {
    // Free 3+9=12, Enterprise 4+2=6, none 5
    expect(h.columns.map((x) => [x.name, x.total])).toEqual([['Free', 12], ['Enterprise', 6], ['No segment', 5]])
    expect(h.columns.at(-1)?.key).toBe(NO_SEGMENT)
  })
  it('has a row per theme in the order given, with counts per column', () => {
    expect(h.rows.map((r) => [r.theme.label, r.cells, r.total])).toEqual([
      ['Report exports time out', [3, 4, 0], 7], ['Bank matching', [0, 2, 5], 7], ['Approvals', [9, 0, 0], 9],
    ])
    expect(h.max).toBe(9)
  })
  it('copes with no themes, and with themes that have no segment data', () => {
    expect(buildHeatmap([])).toEqual({ columns: [], rows: [], max: 0 })
    const bare = buildHeatmap([theme({ segments: [] })])
    expect(bare.columns).toEqual([])
    expect(bare.rows[0].cells).toEqual([])
    expect(bare.max).toBe(0)
  })
})

describe('cellStrength', () => {
  it('is zero for an empty cell and grows with the count without ever hiding a non-empty one', () => {
    expect(cellStrength(0, 9)).toBe(0)
    expect(cellStrength(3, 0)).toBe(0)
    expect(cellStrength(1, 9)).toBeGreaterThan(0.15)
    expect(cellStrength(9, 9)).toBe(1)
    expect(cellStrength(4, 9)).toBeGreaterThan(cellStrength(1, 9))
  })
})

describe('csvCell', () => {
  it('leaves plain values alone and quotes commas, quotes and line breaks', () => {
    expect(csvCell('plain')).toBe('plain')
    expect(csvCell(7)).toBe('7')
    expect(csvCell(null)).toBe('')
    expect(csvCell('a, b')).toBe('"a, b"')
    expect(csvCell('say "hi"')).toBe('"say ""hi"""')
    expect(csvCell('line\nbreak')).toBe('"line\nbreak"')
  })
  it('stops customer words from running as a spreadsheet formula', () => {
    expect(csvCell('=HYPERLINK("http://evil.example")')).toBe('"\'=HYPERLINK(""http://evil.example"")"')
    expect(csvCell('+1 555 0100')).toBe("'+1 555 0100")
    expect(csvCell('-2 degrees')).toBe("'-2 degrees")
    expect(csvCell('@sum')).toBe("'@sum")
    expect(csvCell(-3)).toBe('-3') // a real negative number is not text
  })
})

describe('reportCsv', () => {
  const lines = reportCsv([a, b]).trimEnd().split('\r\n')
  it('has a header and one row per theme, ranked', () => {
    expect(lines).toHaveLength(3)
    expect(lines[0]).toBe('Rank,Theme,Description,Business impact,Mentions,Sources,Average severity,Sentiment,Pain points,Feature requests,Segments')
    expect(lines[1]).toBe('1,Report exports time out,Large reports fail.,100,7,5,3.6,negative,6,1,Enterprise (4); Free (3)')
    expect(lines[2].startsWith('2,Bank matching,')).toBe(true)
  })
  it('ends with a line break and copes with no themes', () => {
    expect(reportCsv([a]).endsWith('\r\n')).toBe(true)
    expect(reportCsv([]).trimEnd().split('\r\n')).toHaveLength(1)
  })
})

describe('reportMarkdown', () => {
  const md = reportMarkdown('Month-end research', [a, b], new Date('2026-10-25T10:00:00Z'))
  it('has a title, the date, a table and a section per theme', () => {
    expect(md).toContain('# Problem space report: Month-end research')
    expect(md).toContain('Generated 2026-10-25.')
    expect(md).toContain('| 1 | Report exports time out | 100 | 7 | 5 | 3.6 | negative |')
    expect(md).toContain('## 2. Bank matching')
    expect(md).toContain('- Segments: Enterprise (4); Free (3)')
    expect(md).toContain('- Use cases: Monthly reporting (4)')
  })
  it('keeps a pipe in a theme name from breaking the table', () => {
    expect(reportMarkdown('x', [theme({ label: 'A | B' })])).toContain('| 1 | A \\| B |')
  })
  it('says so when there are no themes', () => {
    expect(reportMarkdown('x', [])).toContain('No themes yet.')
  })
  it('uses singular words for one of something', () => {
    const one = reportMarkdown('x', [theme({ frequency: 1, sources: 1, kinds: { pain_point: 1, feature_request: 1 } })])
    expect(one).toContain('1 mention across 1 source')
    expect(one).toContain('1 pain point, 1 feature request')
  })
})

describe('fileSlug', () => {
  it('makes a safe file name and never an empty one', () => {
    expect(fileSlug('Month-end research / Q4!')).toBe('month-end-research-q4')
    expect(fileSlug('Pelanggan: Cabaran Utama')).toBe('pelanggan-cabaran-utama')
    expect(fileSlug('???')).toBe('report')
    expect(fileSlug('???', 'themes')).toBe('themes')
  })
})

describe('downloadText', () => {
  it('saves the text under the file name, with a byte-order mark for CSV only', async () => {
    const made: Blob[] = []
    URL.createObjectURL = vi.fn((b: Blob) => (made.push(b), 'blob:x')) as never
    URL.revokeObjectURL = vi.fn() as never
    let saved: { href: string; download: string } | null = null
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      saved = { href: this.href, download: this.download }
    })
    downloadText('themes.csv', 'a,b', 'text/csv')
    downloadText('report.md', '# hi', 'text/markdown')
    expect(saved).toEqual({ href: 'blob:x', download: 'report.md' }) // the last click
    expect(click).toHaveBeenCalledTimes(2)
    // Blob.text() would strip the mark, so look at the raw bytes: EF BB BF is the UTF-8 byte-order mark.
    expect([...new Uint8Array(await made[0].arrayBuffer()).slice(0, 5)]).toEqual([0xef, 0xbb, 0xbf, 0x61, 0x2c])
    expect([...new Uint8Array(await made[1].arrayBuffer()).slice(0, 2)]).toEqual([0x23, 0x20])
    expect(made[0].type).toContain('text/csv')
    expect(document.querySelector('a[download]')).toBeNull() // the link is removed again
    click.mockRestore()
  })
})

describe('shortSegment', () => {
  it('keeps short names, shortens long ones and renames the empty segment', () => {
    expect(shortSegment('Free')).toBe('Free')
    expect(shortSegment('Pro')).toBe('Pro')
    expect(shortSegment('Enterprise')).toBe('Ente.')
    expect(shortSegment('Mid-Market')).toBe('Mid-.')
    expect(shortSegment('No segment')).toBe('None')
  })
})
