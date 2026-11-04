// Port of plugins/skill-eval/hooks/skill-forced-eval-hook.sh (MIT, Umputun).
import { Plugin } from "@opencode/plugin"

const marker = "cc-thingz/skill-eval"

export default Plugin.define({
  id: "cc-thingz.skill-eval",
  async setup(ctx) {
    // Admission metadata, not canonical text: attachments and mention offsets stay intact.
    await ctx.session.hook("prompt", (event) => {
      event.metadata = { ...event.metadata, [marker]: true }
    })
    await ctx.session.hook("context", async (event) => {
      const messages = await ctx.session.context({ sessionID: event.sessionID })
      const request = messages.findLast((message) =>
        ["user", "synthetic", "shell", "compaction", "assistant"].includes(message.type))
      if (request?.type !== "user" || request.metadata?.[marker] !== true) return
      // Durable across plugin reload; no process-global session state or prompt side effects.
      const pending = []
      for (const message of messages) {
        if (message.type !== "user" || message.metadata?.[marker] !== true) continue
        const key = `handled/${event.sessionID}/${message.id}`
        if (await ctx.storage.get(key) !== true) pending.push(key)
      }
      if (!pending.length) return
      const loaded = [...new Set(messages.flatMap((message) =>
        message.type === "skill" ? [message.skill] :
          message.type === "user" ? (message.skills ?? []).map((skill) => skill.id) : []))]
      event.system.push({ type: "text", text: `INSTRUCTION: MANDATORY SKILL ACTIVATION

For the ${pending.length} new user request(s) in this dispatch (including slash-command prompts), check available skills for relevance before proceeding.
If any are relevant: briefly state which and why; immediately activate ALL relevant skills not already available in this session using the skill tool with {id: "skill-id"}; then proceed with the task.
Use already-loaded skills without loading them again. Do not activate unrelated skills or activate skills recursively merely to satisfy this reminder.
If no skills are relevant, proceed directly.
Already-loaded skill IDs in the current context: ${loaded.length ? loaded.join(", ") : "none"}.` })
      // Once per admitted request's first dispatch, not an exactly-once provider delivery claim.
      for (const key of pending) await ctx.storage.set(key, true)
    })
  },
})
