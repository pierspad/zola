#!/usr/bin/env node
// Adapter must execute the selected shipped frontend, not reimplement its search.
import fs from 'node:fs';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {performance} from 'node:perf_hooks';
const specification = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const hash = path => crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex');
const adapter = await import(pathToFileURL(specification.adapter));
if (typeof adapter.setup !== 'function') throw Error('adapter must export setup(specification)');
const search = await adapter.setup(specification);
const samples = [];
for (const query of specification.queries) {
  for (let i = 0; i < 20; i++) await search(query.text);
  const times = [];
  const cpuTimes = [];
  let actual;
  for (let i = 0; i < 100; i++) {
    const cpuStart = process.cpuUsage();
    const start = performance.now();
    actual = await search(query.text);
    times.push(performance.now() - start);
    const cpu = process.cpuUsage(cpuStart);
    cpuTimes.push((cpu.user + cpu.system) / 1000);
  }
  if (!Array.isArray(actual) || actual.some(x => typeof x !== 'string')) throw Error('search adapter must return ranked URL strings');
  const expected = query.expected;
  const membership = expected.every(x => actual.includes(x)) && (query.allow_extra === true || actual.every(x => expected.includes(x)));
  const ranking = !query.ranked_prefix || query.ranked_prefix.every((x, i) => actual[i] === x);
  const rawTimes = [...times];
  times.sort((a, b) => a - b);
  samples.push({query: query.text, expected, actual, status: membership && ranking ? 'pass' : 'fail',
    warmups: 20, iterations: times.length, median_ms: (times[49] + times[50]) / 2, p95_ms: times[Math.ceil(times.length * .95) - 1], raw_ms: rawTimes, raw_cpu_ms: cpuTimes});
}
console.log(JSON.stringify({status: samples.every(x => x.status === 'pass') ? 'pass' : 'fail',
  measurement: 'Node process executing supplied shipped-frontend adapter; not browser latency or LCP',
  runtime: process.version, peak_process_rss_bytes: process.resourceUsage().maxRSS * (process.platform === 'darwin' ? 1 : 1024),
  adapter_sha256: hash(specification.adapter), source_files: specification.source_files.map(path => ({path, sha256: hash(path)})), samples}));
