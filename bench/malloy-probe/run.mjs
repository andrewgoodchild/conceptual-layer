import {Malloy, Runtime} from '@malloydata/malloy';
import {DuckDBConnection} from '@malloydata/db-duckdb';
import fs from 'fs';
const conn = new DuckDBConnection('duckdb', process.argv[2] + '/company.duckdb');
const files = {readURL: async (url) => fs.readFileSync(url.toString().replace('file://',''), 'utf8')};
const runtime = new Runtime({urlReader: files, connection: conn});
const model = process.argv[2] + '/company.malloy';
const queries = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
for (const [name, q] of queries) {
  try {
    const runner = runtime.loadModel(new URL('file://' + model)).loadQuery(q);
    const res = await runner.run();
    const rows = res.data.toObject();
    console.log(JSON.stringify({name, rows: rows.slice(0,4), sql: (await runner.getSQL()).replace(/\s+/g,' ').slice(0,300)}));
  } catch (e) {
    console.log(JSON.stringify({name, error: String(e.message||e).split('\n')[0].slice(0,200)}));
  }
}
await conn.close();
