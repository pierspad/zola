// Executes the unmodified scoring/rendering path in the shipped personal frontend.
import fs from 'node:fs';
import vm from 'node:vm';
export async function setup(specification) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {innerHTML: '', style: {}, value: '',
      addEventListener() {}, removeEventListener() {}, querySelectorAll() { return []; },
      classList: {add() {}, remove() {}, toggle() {}}, contains() { return false; }});
    return elements.get(id);
  };
  const source = fs.readFileSync(specification.frontend, 'utf8');
  const anchor = '  // Delega eventi click sul contenitore risultati';
  if (source.split(anchor).length !== 2) throw Error('Frontend instrumentation anchor changed; review adapter');
  // Export the real closure functions only. Clearing last-query suppression forces
  // the real query work on each iteration; debounce/event scheduling is excluded.
  const instrumented = source.replace(anchor,
    '  globalThis.__benchmark = {loadSearchData, run(term) { currentTerm = ""; performSearch(term); }};\n' + anchor);
  const index = JSON.parse(fs.readFileSync(specification.index, 'utf8'));
  const context = vm.createContext({console, setTimeout, clearTimeout,
    document: {readyState: 'loading', documentElement: {lang: specification.language || 'it'},
      getElementById: element, addEventListener() {}},
    window: {addEventListener() {}}, fetch: async () => ({ok: true, json: async () => index})});
  vm.runInContext(instrumented, context, {filename: specification.frontend, timeout: 5000});
  context.initSearch();
  await context.__benchmark.loadSearchData();
  return term => {
    context.__benchmark.run(term);
    return [...element('search-results').innerHTML.matchAll(/data-url="([^"]*)"/g)].map(match => match[1]);
  };
}
