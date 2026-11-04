import assert from "node:assert/strict"
import test from "node:test"
import plugin from "../integrations/opencode/skill-eval/index.ts"

// Only the hook boundary is mocked. Any unexpected API use (including activation,
// prompt submission, events or model generation) fails rather than recursing.
async function harness(storage = new Map<string, unknown>()) {
  const hooks: Record<string, (event: any) => Promise<void> | void> = {}
  const histories = new Map<string, any[]>()
  await plugin.setup({
    session: {
      hook: async (name: string, callback: (event: any) => void) => {
        hooks[name] = callback
      },
      context: async ({ sessionID }: { sessionID: string }) => histories.get(sessionID) ?? [],
    },
    storage: { get: async (key: string) => storage.get(key),
      set: async (key: string, value: unknown) => { storage.set(key, value) } },
  } as unknown as Parameters<typeof plugin.setup>[0])
  return { hooks, histories, storage,
    async admit(sessionID: string, id: string, prompt: any = { text: "request" }) {
      const event = { sessionID, messageID: id, prompt, metadata: { origin: "fixture" }, delivery: "queue" }
      const before = structuredClone(event)
      await hooks.prompt(event)
      assert.deepEqual(event.prompt, before.prompt)
      assert.equal(event.delivery, before.delivery)
      assert.equal(event.metadata.origin, "fixture")
      const history = histories.get(sessionID) ?? []
      history.push({ type: "user", id, ...prompt, metadata: event.metadata })
      histories.set(sessionID, history)
      return event
    },
    async dispatch(sessionID: string) {
      const event = { sessionID, system: [{ type: "text", text: "original" }], messages: [] }
      await hooks.context(event)
      assert.deepEqual(event.system[0], { type: "text", text: "original" })
      assert.deepEqual(event.messages, [])
      return event.system.slice(1)
    },
  }
}

test("ordinary prompt and attachments/mentions preserve every offset", async () => {
  const h = await harness()
  await h.admit("s", "u", { text: "@review file", files: [{ uri: "file:///a b", mention: { start: 8, end: 12 } }],
    agents: [{ id: "review", mention: { start: 0, end: 7 } }], skills: [{ id: "x" }] })
  assert.equal((await h.dispatch("s")).length, 1)
  assert.deepEqual(Object.keys(h.hooks).sort(), ["context", "prompt"])
})

test("slash executor admission is one prompt, tools continuation and retry add none", async () => {
  const h = await harness()
  await h.admit("s", "command", { text: 'Load skill x; arguments: "a b"  $(literal)' })
  assert.equal((await h.dispatch("s")).length, 1)
  assert.equal((await h.dispatch("s")).length, 0)
  h.histories.get("s")!.push({ type: "assistant", id: "a", parts: [{ type: "tool" }] })
  assert.equal((await h.dispatch("s")).length, 0)
  await h.admit("s", "next")
  assert.equal((await h.dispatch("s")).length, 1)
})

test("sessions isolated and durable across plugin reload", async () => {
  const h = await harness()
  await h.admit("a", "same-id")
  await h.admit("b", "same-id")
  assert.equal((await h.dispatch("a")).length, 1)
  assert.equal((await h.dispatch("b")).length, 1)
  const reload = await harness(h.storage)
  reload.histories.set("a", h.histories.get("a")!)
  assert.equal((await reload.dispatch("a")).length, 0)
})

test("coalesced admissions share one reminder and each is consumed once", async () => {
  const h = await harness()
  await h.admit("s", "u1")
  await h.admit("s", "u2")
  assert.equal((await h.dispatch("s")).length, 1)
  assert.equal(h.storage.size, 2)
  assert.equal((await h.dispatch("s")).length, 0)
})

test("already loaded IDs are session-local; plugin never activates skills", async () => {
  const h = await harness()
  h.histories.set("s", [{ type: "skill", skill: "x" }, { type: "skill", skill: "x" }])
  await h.admit("s", "u")
  const reminder = await h.dispatch("s")
  assert.match(reminder[0].text, /current context: x\./)
  await h.admit("other", "u")
  assert.match((await h.dispatch("other"))[0].text, /current context: none\./)
  await h.admit("composer", "u", { text: "@x", skills: [{ id: "x", text: "loaded body" }] })
  assert.match((await h.dispatch("composer"))[0].text, /current context: x\./)
})

test("no matching skill still allows direct progress, no registry or tool call", async () => {
  const h = await harness()
  await h.admit("s", "u", { text: "Say hello" })
  assert.equal((await h.dispatch("s")).length, 1)
  assert.equal(h.storage.size, 1)
})

test("synthetic, shell, compaction and internal child inputs bypass admission", async () => {
  const h = await harness()
  for (const type of ["synthetic", "shell", "compaction", "user"]) {
    h.histories.set(type, [{ type, id: type }])
    assert.equal((await h.dispatch(type)).length, 0)
  }
  // An explicitly admitted child request follows the ordinary prompt contract.
  await h.admit("child", "u")
  assert.equal((await h.dispatch("child")).length, 1)
})

test("failed admission causes no storage writes; API errors are not swallowed", async () => {
  const h = await harness()
  await h.hooks.prompt({ sessionID: "s", messageID: "failed", prompt: { text: "bad attachment" } })
  assert.equal(h.storage.size, 0)
  assert.equal((await h.dispatch("s")).length, 0)
  await h.admit("s", "ok")
  h.storage.get = () => { throw new Error("storage failed") }
  await assert.rejects(h.dispatch("s"), /storage failed/)
})
