import { useMemo, type ReactNode, type RefObject, type MutableRefObject } from "react"
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
  type ChatModelRunOptions,
  type ChatModelRunResult,
} from "@assistant-ui/react"

export interface ChatImage {
  name: string
  data: string // base64
  mime: string
}

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
 * Rendering strategy: decouple network arrival from display via a paced
 * typewriter. A background reader appends incoming tokens to a shared buffer
 * as fast as they arrive, and a yield loop reveals characters at ~30fps. The
 * adapter never yields in bursts — updates are always smooth.
 */
function buildAdapter(
  sessionIdRef: RefObject<string | null>,
  imagesRef: MutableRefObject<ChatImage[]>,
): ChatModelAdapter {
  return {
    async *run({
      messages,
      abortSignal,
    }: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult, void> {
      const lastMessage = messages[messages.length - 1]
      if (!lastMessage || lastMessage.role !== "user") return

      const userText = lastMessage.content
        .filter((p): p is { type: "text"; text: string } => p.type === "text")
        .map((p) => p.text)
        .join("\n")

      if (!userText.trim() && imagesRef.current.length === 0) return

      const images = imagesRef.current.slice()
      imagesRef.current = []

      // X-App-Token + Supabase JWT for backend auth; both are added by
      // buildAuthHeaders so this stays consistent with the rest of the app.
      const { buildAuthHeaders, apiUrl } = await import("@/lib/utils")
      const headers = await buildAuthHeaders({ "Content-Type": "application/json" })

      const res = await fetch(apiUrl("/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify({
          message: userText,
          session_id: sessionIdRef.current,
          images: images.length > 0 ? images : undefined,
        }),
        signal: abortSignal,
      })

      if (!res.ok || !res.body) {
        throw new Error(`Chat request failed: ${res.status}`)
      }

      // Shared state between the reader task and the yield loop
      let fullText = ""
      let streamDone = false
      let streamError: Error | null = null

      // Background task: read the SSE stream as fast as the network delivers
      // and append tokens to `fullText`. No yielding here — rendering pace is
      // controlled entirely by the yield loop below.
      const readerTask = (async () => {
        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ""
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

              if (event.type === "session" && event.session_id) {
                sessionIdRef.current = event.session_id
              } else if (event.type === "token" && event.content) {
                fullText += event.content
              } else if (event.type === "error") {
                streamError = new Error(event.message || "Stream error")
                return
              }
              // tool_start / tool_end / done: ignored — display is driven by
              // fullText growth only.
            }
          }
        } catch (e) {
          if ((e as Error).name !== "AbortError") {
            streamError = e as Error
          }
        } finally {
          try {
            reader.releaseLock()
          } catch {
            /* noop */
          }
          streamDone = true
        }
      })()

      // Paced yield loop: ~30fps. Each frame reveals enough chars to catch
      // up within ~500ms (15 frames), so if the network is ahead the reveal
      // speeds up; if it's keeping pace the reveal stays smooth. After the
      // stream ends, the remaining buffer drains in the same ~500ms.
      const FRAME_MS = 33
      const CATCH_UP_FRAMES = 15
      let displayed = 0
      let lastYielded = ""

      try {
        while (true) {
          if (streamError) throw streamError
          if (abortSignal.aborted) break

          const remaining = fullText.length - displayed
          if (remaining > 0) {
            const advance = Math.max(2, Math.ceil(remaining / CATCH_UP_FRAMES))
            displayed = Math.min(fullText.length, displayed + advance)
            const slice = fullText.slice(0, displayed)
            if (slice !== lastYielded) {
              lastYielded = slice
              yield { content: [{ type: "text", text: slice }] }
            }
          }

          if (streamDone && displayed >= fullText.length) break

          await new Promise((resolve) => setTimeout(resolve, FRAME_MS))
        }

        // Wait for the reader to fully finish (usually already done)
        await readerTask

        if (streamError) throw streamError

        // Final yield to ensure the full text is committed exactly once
        if (fullText !== lastYielded) {
          yield { content: [{ type: "text", text: fullText }] }
        }
      } finally {
        // Ensure the reader task is settled even if we threw
        await readerTask.catch(() => {})
      }
    },
  }
}

interface ChatRuntimeProviderProps {
  sessionIdRef: RefObject<string | null>
  imagesRef: MutableRefObject<ChatImage[]>
  children: ReactNode
}

export function ChatRuntimeProvider({
  sessionIdRef,
  imagesRef,
  children,
}: ChatRuntimeProviderProps) {
  const adapter = useMemo(() => buildAdapter(sessionIdRef, imagesRef), [sessionIdRef, imagesRef])
  const runtime = useLocalRuntime(adapter)
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  )
}
