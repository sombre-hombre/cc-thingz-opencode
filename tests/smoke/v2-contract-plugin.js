import { writeFile } from "node:fs/promises"

// Test-only introspection, not part of the installation manifest.
export default {
  id: "cc-thingz-contract-probe",
  async setup(ctx) {
    const directory = ctx.location.directory
    const tools = await ctx.tool.list()
    await writeFile(`${directory}/tool-schemas.json`, JSON.stringify(tools, null, 2))
    await ctx.session.hook("prompt", async (event) => {
      const checks = [
        ["plan-review", "edit", "fixture.txt", "deny"],
        ["external-plan-review", "edit", "fixture.txt", "deny"],
        ["external-plan-review", "edit", "/tmp/opencode/external-plan-review-contract/prompt.txt", "allow"],
        ["external-plan-review", "edit", "/tmp/opencode/unrelated-project.txt", "deny"],
      ]
      const results = []
      for (const [agent, action, resource, expected] of checks) {
        let actual = "allow"
        try {
          await ctx.permission.assert({ sessionID: event.sessionID, agent, action, resources: [resource] })
        } catch {
          actual = "deny"
        }
        results.push({ agent, action, resource, expected, actual })
        if (actual !== expected) throw new Error(`Unexpected permission result: ${agent} ${resource}`)
      }
      await writeFile(`${directory}/permission-results.json`, JSON.stringify(results, null, 2))
    })
    await ctx.session.hook("context", async (event) => {
      await writeFile(`${directory}/request-tool-schemas.json`, JSON.stringify(event.tools, null, 2))
      await writeFile(`${directory}/request-system.json`, JSON.stringify(event.system, null, 2))
    })
  },
}
