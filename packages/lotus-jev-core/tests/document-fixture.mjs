/** Exercise the production document-reader expression against rendered DOM observations. */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const expression = readFileSync(0, 'utf8')
const element = ({ excluded = null, cssVisible = true, label = '', href, top = 0 } = {}) => ({
  closest: selector => selector.split(',').includes(excluded) ? {} : null,
  checkVisibility: () => cssVisible,
  getBoundingClientRect: () => ({ top, bottom: top + 20 }),
  innerText: label, href,
  getAttribute: () => '',
})
const textNode = (textContent, parentElement = element()) => ({ textContent, parentElement })
const read = (nodes, links = [], body = {}) => {
  let index = 0
  const document = { body, title: 'All listings',
    createTreeWalker: () => ({ nextNode: () => nodes[index++] ?? null }),
    querySelectorAll: () => links }
  return JSON.parse(JSON.stringify(vm.runInNewContext(expression, {
    document, location: { href: 'https://listings.example/all' }, NodeFilter: { SHOW_TEXT: 4 }, innerHeight: 600,
  })))
}

const evidence = read([
  textNode('First visible listing'),
  textNode('Offscreen listing eighteen', element({ top: 5000 })),
  textNode('CSS-hidden text', element({ cssVisible: false })),
  textNode('Script source', element({ excluded: 'script' })),
  textNode('Stylesheet source', element({ excluded: 'style' })),
  textNode('Template source', element({ excluded: 'template' })),
  textNode('Hidden or inert content', element({ excluded: '[inert]' })),
], [
  element({ label: 'Offscreen listing', href: 'https://listings.example/18', top: 5000 }),
  element({ label: 'Hidden link', href: 'https://listings.example/hidden', excluded: '[aria-hidden="true"]' }),
])
assert.equal(evidence.text, 'First visible listing\nOffscreen listing eighteen')
assert.deepEqual(evidence.links, [{ text: 'Offscreen listing', href: 'https://listings.example/18' }])
assert.equal(evidence.truncated, false)
assert.equal(read([], [], null), null)

const oversized = read([textNode('x'.repeat(25000))])
assert.ok(oversized.text.length > 0 && oversized.text.length <= 24000)
assert.equal(oversized.truncated, true)
const manyNodes = read(Array.from({ length: 30 }, () => textNode('n'.repeat(1000))))
assert.ok(manyNodes.text.length <= 24000)
assert.equal(manyNodes.truncated, true)

const manyLinks = read([], Array.from({ length: 201 }, (_, i) =>
  element({ label: `Listing ${i}`, href: `https://listings.example/${i}` })))
assert.equal(manyLinks.links.length, 200)
assert.equal(manyLinks.truncated, true)
const longHref = read([], [element({ label: 'Too long', href: 'https://listings.example/' + 'x'.repeat(4096) })])
assert.deepEqual(longHref.links, [])
assert.equal(longHref.truncated, true)
const longLabel = read([], [element({ label: 'x'.repeat(301), href: 'https://listings.example/1' })])
assert.equal(longLabel.links[0].text.length, 300)
assert.equal(longLabel.truncated, true)
