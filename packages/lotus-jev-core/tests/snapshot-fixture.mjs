/** Execute the production snapshot against fixed DOM observations without launching a browser. */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const pageUrl = 'https://listings.example/results/'
const group = { children: [], innerText: 'Fixture controls', parentElement: null,
  matches: () => false, querySelector: () => null, closest: () => null }
const element = (tagName, label, options = {}) => {
  const attributes = { 'aria-label': label, ...options.attributes }
  return {
    tagName, type: '', isConnected: true, parentElement: group, children: [], childNodes: [], labels: [],
    innerText: label, classList: { contains: () => false }, scrollTop: 0, scrollLeft: 0,
    checkVisibility: () => true, getBoundingClientRect: () => ({ x: 10, y: 10, width: 100, height: 20 }),
    getAttribute: name => attributes[name] ?? null,
    hasAttribute: name => name in attributes,
    closest: () => null, matches(selector) { return selector === ':disabled' && !!this.disabled },
    contains(other) { return other === this },
    ...options,
  }
}
const controls = [
  element('INPUT', 'Disabled text', { type: 'text', disabled: true, value: 'Ready for QA', readOnly: false }),
  element('INPUT', 'Disabled checkbox', { type: 'checkbox', disabled: true, checked: true, value: 'on', readOnly: false }),
  element('INPUT', 'Disabled radio', { type: 'radio', disabled: true, checked: false, value: 'choice', readOnly: false }),
  element('TEXTAREA', 'Readonly notes', { disabled: true, value: 'Keep my notes', readOnly: true }),
  element('INPUT', 'Password', { type: 'password', disabled: true, value: 'must-not-leak' }),
  element('INPUT', 'File', { type: 'file', disabled: true, value: 'must-not-leak' }),
  element('INPUT', 'Hidden', { type: 'hidden', disabled: true, value: 'must-not-leak' }),
]
const link = element('A', 'View listing', { attributes: { href: '../cars/42?currency=USD' },
  href: new URL('../cars/42?currency=USD', pageUrl).href })
const sortable = element('TH', 'Last Name', { cursor: 'pointer', querySelector: () => null,
  getBoundingClientRect: () => ({ x: 150, y: 10, width: 100, height: 20 }) })
const staticHeader = element('TH', 'Static header', { querySelector: () => null })
const candidates = [...controls, link]
group.children = [...candidates, sortable, staticHeader]
const document = {
  body: {}, title: 'Fixture', documentElement: { scrollHeight: 600 }, activeElement: null,
  querySelectorAll(selector) {
    if (selector.startsWith('a,button,input,')) return candidates
    if (selector === 'input,textarea,select') return controls
    if (selector === 'span,div,th') return [sortable, staticHeader]
    return []
  },
  getElementById: () => null, elementFromPoint: x => x > 150 ? sortable : link,
  createTreeWalker: () => ({ nextNode: () => null }), createRange: () => ({}),
}
const context = { document, window: {}, location: { href: pageUrl }, performance: { timeOrigin: 1 },
  scrollX: 0, scrollY: 0, innerWidth: 800, innerHeight: 600, NodeFilter: { SHOW_TEXT: 4 },
  getComputedStyle: e => ({ cursor: e.cursor || 'default', overflowY: 'visible' }) }
const snapshot = JSON.parse(JSON.stringify(vm.runInNewContext(readFileSync(process.argv[2], 'utf8'), context)))
const byLabel = Object.fromEntries(snapshot.disabled_controls.map(control => [control.label, control]))
assert.equal(byLabel['Disabled text'].value, 'Ready for QA')
assert.equal(byLabel['Disabled text'].readonly, false)
assert.equal(byLabel['Disabled checkbox'].checked, 'true')
assert.equal(byLabel['Disabled radio'].checked, 'false')
assert.equal(byLabel['Readonly notes'].value, 'Keep my notes')
assert.equal(byLabel['Readonly notes'].readonly, true)
assert.equal(Object.keys(byLabel).length, 4)
assert.ok(!JSON.stringify(snapshot).includes('must-not-leak'))
assert.equal(snapshot.actions.find(action => action.role === 'link').href,
  'https://listings.example/cars/42?currency=USD')
assert.ok(!snapshot.actions.some(action => action.label.startsWith('Disabled')))
assert.equal(snapshot.actions.find(action => action.label === 'Last Name').kind, 'click')
assert.ok(!snapshot.actions.some(action => action.label === 'Static header'))
