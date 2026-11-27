import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";
import STRINGS from "./strings";

// The facts card must not invent anything: every fact that contains a number
// has to appear word for word in the knowledge base.
const KB_DIR = join(__dirname, "..", "..", "data", "knowledge_base");
const knowledgeBase = readdirSync(KB_DIR)
  .filter((name) => name.endsWith(".md"))
  .map((name) => readFileSync(join(KB_DIR, name), "utf-8"))
  .join("\n");

test.each(STRINGS.facts.filter((fact) => /\d/.test(fact.value)).map((fact) => fact.value))(
  "fact %s is in the knowledge base",
  (value) => {
    expect(knowledgeBase).toContain(value);
  },
);
