import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { test } from "node:test";

test("migration comments cannot be mistaken for remote D1 statement boundaries", async () => {
  // The remote /query API rejects a block comment containing a semicolon with
  // error 7500 (even before SELECT 1). Local SQLite and Wrangler's local splitter
  // accept it. Guard the checked-in SQL against this verified platform boundary;
  // runtime tests separately execute all migrations and verify their effects.
  const directory = new URL("../migrations/", import.meta.url);
  for (const name of (await readdir(directory)).filter((name) => name.endsWith(".sql"))) {
    const sql = await readFile(new URL(name, directory), "utf8");
    for (const comment of sql.match(/\/\*[\s\S]*?\*\/|--[^\n]*/g) ?? [])
      assert.ok(!comment.includes(";"), `${name}: keep semicolons out of migration comments`);
  }
});
