// Fixture-only consumer of Zola's documented Fuse JSON array contract.
import fs from 'node:fs';
import crypto from 'node:crypto';
import Fuse from './vendor/fuse-7.1.0.mjs';
const runtime = new URL('./vendor/fuse-7.1.0.mjs', import.meta.url);
export async function setup(specification) {
  if (crypto.createHash('sha256').update(fs.readFileSync(runtime)).digest('hex') !==
      'f9ac60acd35c2538e9d2d146c4fae4b3e9c024bf99e82ef63592e6d872b0064b') throw Error('Fuse runtime hash mismatch');
  const records = JSON.parse(fs.readFileSync(specification.index, 'utf8'));
  if (records.length !== specification.expected_count) throw Error('index membership count mismatch');
  const actual = new Set(records.map(record => record.url));
  if (actual.size !== records.length || specification.expected_urls.some(url => !actual.has(url))) throw Error('index URL membership mismatch');
  // Fixed fixture policy: exact substring matches, diacritic folding, title priority.
  const fuse = new Fuse(records, {keys: [{name:'title', weight:0.8}, {name:'body', weight:0.2}],
    threshold:0, ignoreLocation:true, ignoreDiacritics:true, includeScore:true});
  return text => fuse.search(text).map(result => result.item.url);
}
