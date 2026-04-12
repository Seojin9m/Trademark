import { useMemo, type ReactNode, type RefObject } from "react"
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
  type ChatModelRunOptions,
  type ChatModelRunResult,
} from "@assistant-ui/react"

/**
 * Builds a ChatModelAdapter that streams from our custom backend at /api/chat.
 *
 * Backend protocol (SSE):
 *   data: {"type": "session", "session_id": "..."}
 *   data: {"type": "tool_start", "tool": "...", "input": "..."}
 *   data: {"type": "tool_end", "tool": "..."}
 *   data: {"type": "token", "content": "..."}
 *   data: {"type": "done"}
 *   data: {"type": "error", "message": "..."}
 *
 * The adapter only sends the *latest* user message — backend session state lives
 * server-side and is keyed by session_id. assistant-ui still keeps a client copy
 * for rendering, but server context is the source of truth for the model.
 */
function buildAdapter(
  sessionIdRef: RefObject<string | null>,
): ChatModelAdapter {
  return {
    async *run({
      messages,
      abortSignal,
    }: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult, void> {
      // Extract the last user message text
      const lastMessage = messages[messages.length - 1]
      if (!lastMessage || lastMessage.role !== "user") return

      const userText = lastMessage.content
        .filter((p): p is { type: "text"; text: string } => p.type === "text")
        .map((p) => p.text)
        .join("\n")

      if (!userText.trim()) return

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userText,
          session_id: sessionIdRef.current,
        }),
        signal: abortSignal,
      })

      if (!res.ok || !res.body) {
        throw new Error(`Chat request failed: ${res.status}`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let accumulated = ""
      const toolNames: string[] = []
      let lastYieldedText = ""
      let lastYieldTime = 0
      // Throttle token yields. Every yield triggers a full re-parse of the
      // growing message by ReactMarkdown, which is the real source of the
      // streaming lag. At ~12 yields/sec the user still sees smooth growth
      // but we do ~10× less work.
      const MIN_YIELD_INTERVAL_MS = 80

      // Helper that builds the current ChatModelRunResult content array.
      // Tool calls are rendered as a small prefix in the text since assistant-ui's
      // tool-call rendering pipeline expects a different protocol — keeping it as
      // text gives us a single render path and matches our existing UX.
      const buildResult = (): ChatModelRunResult => {
        const toolPrefix = toolNames.length
          ? toolNames.map((t) => `🔧 ${t.replace(/^get_/, "").replace(/_/g, " ")}`).join("\n") + "\n\n"
          : ""
        return {
          content: [{ type: "text", text: toolPrefix + accumulated }],
        }
      }

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split("\n")
          buffer = lines.pop() || ""

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue
            const jsonStr = line.slice(6).trim()
            if (!jsonStr) continue

            let event: {
              type: string
              session_id?: string
              tool?: string
              content?: string
              message?: string
            }
            try {
              event = JSON.parse(jsonStr)
            } catch {
              continue
            }

            switch (event.type) {
              case "session":
                if (event.session_id) {
                  sessionIdRef.current = event.session_id
                }
                break

              case "tool_start":
                if (event.tool && !toolNames.includes(event.tool)) {
                  toolNames.push(event.tool)
                  yield buildResult()
                }
                break

              case "token":
                if (event.content) {
                  accumulated += event.content
                  // Throttle: skip the yield if we yielded recently.
                  // The finally block below guarantees the final state ships,
                  // so dropped intermediate yields never lose data.
                  const now = performance.now()
                  if (
                    accumulated !== lastYieldedText &&
                    now - lastYieldTime >= MIN_YIELD_INTERVAL_MS
                  ) {
                    lastYieldedText = accumulated
                    lastYieldTime = now
                    yield buildResult()
                  }
                }
                break

              case "error":
                throw new Error(event.message || "Stream error")

              case "tool_end":
              case "done":
                break
            }
          }
        }
      } finally {
        reader.releaseLock?.()
      }

      // Final yield to make sure the last accumulated text is committed
      yield buildResult()
    },
  }
}

interface ChatRuntimeProviderProps {
  sessionIdRef: RefObject<string | null>
  children: ReactNode
}

export function ChatRuntimeProvider({
  sessionIdRef,
  children,
}: ChatRuntimeProviderProps) {
  // Adapter must be stable across renders or useLocalRuntime will reset state.
  const adapter = useMemo(() => buildAdapter(sessionIdRef), [sessionIdRef])
  const runtime = useLocalRuntime(adapter)
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  )
}
